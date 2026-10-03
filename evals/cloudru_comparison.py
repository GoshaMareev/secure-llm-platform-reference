"""Fixed synthetic privacy coverage comparison; every miss is retained in the report."""

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/rag-assistant")]
from secure_rag.cloudru_pii import MAX_RESPONSE_BYTES, CloudruScanClient, ScanUnavailable  # noqa: E402
from secure_rag.guardrails import PiiServiceError  # noqa: E402
from secure_rag.presidio_pii import PresidioHttpRedactor  # noqa: E402

from evals.cloudru_cases import CASES  # noqa: E402

SCANNER_IMAGE = "ghcr.io/cloud-ru-tech/guardrails-llm-filter@sha256:" + (
    "c2365b1c67de00d588192b2bf15b1911f482c13fcff6abcc54aabf14c54e3bf6"
)


def expected_positions(case):
    return {index for start, end in case.spans for index in range(start, end)}


def masked_positions(text, redacted):
    # Remove placeholder characters from the alignment: a coincidental shared
    # letter inside a replacement must not count as an unredacted original.
    redacted = re.sub(r"\[REDACTED_[A-Z_]+\]", "\0", redacted)
    return {
        index
        for tag, start, end, _, _ in SequenceMatcher(None, text, redacted, autojunk=False).get_opcodes()
        if tag in {"replace", "delete"}
        for index in range(start, end)
    }


def score(case, positions):
    gold = expected_positions(case)
    covered = gold & positions
    return {
        "protected_values": sum(set(range(start, end)) <= positions for start, end in case.spans),
        "sensitive_values": len(case.spans),
        "sensitive_characters": len(gold),
        "covered_sensitive_characters": len(covered),
        "extra_masked_characters": len(positions - gold),
        "benign_unchanged": not positions if not gold else None,
    }


class EvaluationScanner(CloudruScanClient):
    """Synthetic-only evaluation needs original spans; production uses scan() summaries."""

    def spans(self, text):
        request = Request(  # noqa: S310 - inherited local-only allowlist and redirect/proxy rejection
            self._url,
            data=json.dumps({"texts": [text]}, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ScanUnavailable("response_limit")
            payload = json.loads(body)
            masked = payload["masked_texts"]
            if not isinstance(masked, list) or len(masked) != 1 or not isinstance(masked[0], str):
                raise ValueError("invalid_masked_text")
            originals = [item["original"] for item in payload["placeholders"]]
            if any(
                not isinstance(value, str) or not value or value not in text or value in masked[0]
                for value in originals
            ):
                raise ValueError("invalid_span")
        except (URLError, OSError, TimeoutError):
            raise ScanUnavailable("service_unavailable") from None
        except (ValueError, TypeError, KeyError):
            raise ScanUnavailable("invalid_response") from None
        positions = set()
        for value in originals:
            for match in re.finditer(re.escape(value), text):
                positions.update(range(match.start(), match.end()))
        return positions


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2) if ordered else None


def aggregate(results, name):
    rows = [row[name] for row in results]
    checked = [row for row in rows if row["status"] == "checked"]
    latency = [row["latency_ms"] for row in rows]
    return {
        "cases": len(rows),
        "checked": len(checked),
        "unavailable": len(rows) - len(checked),
        **{
            field: sum(row.get(field, 0) for row in checked)
            for field in (
                "protected_values",
                "sensitive_values",
                "sensitive_characters",
                "covered_sensitive_characters",
                "extra_masked_characters",
            )
        },
        "benign_unchanged": sum(row.get("benign_unchanged") is True for row in checked),
        "benign_cases": sum(not row["sensitive"] for row in results),
        "latency_p50_ms": percentile(latency, 0.5),
        "latency_p95_ms": percentile(latency, 0.95),
        "miss_ids": [
            row["id"]
            for row in results
            if row["sensitive"]
            and (
                row[name]["status"] != "checked"
                or row[name]["protected_values"] != row[name]["sensitive_values"]
            )
        ],
        "false_positive_ids": [
            row["id"]
            for row in results
            if not row["sensitive"] and row[name].get("benign_unchanged") is False
        ],
    }


def evaluate(scanner, presidio):
    results = []
    for case in CASES:
        row = {"id": case.id, "group": case.group, "sensitive": bool(case.spans)}
        for name, detector in (("cloudru", scanner.spans), ("presidio", presidio.redact)):
            started = time.monotonic()
            try:
                if name == "presidio":
                    sanitized, _ = detector(case.text)
                    positions = masked_positions(case.text, sanitized)
                else:
                    positions = detector(case.text)
                row[name] = {"status": "checked", **score(case, positions)}
            except (ScanUnavailable, PiiServiceError):
                row[name] = {"status": "unavailable"}
            row[name]["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        started = time.monotonic()
        if row["presidio"]["status"] == "checked":
            try:
                row["after_presidio"] = scanner.scan([sanitized]).event()
            except ScanUnavailable as error:
                row["after_presidio"] = {"status": "unavailable", "reason": str(error)}
        else:
            row["after_presidio"] = {"status": "unavailable", "reason": "presidio_unavailable"}
        row["after_presidio"]["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        results.append(row)
    groups = defaultdict(list)
    for row in results:
        groups[row["group"]].append(row)
    manifest = json.dumps([case.manifest() for case in CASES], ensure_ascii=False, sort_keys=True).encode()
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": "64 fixed synthetic cases; full annotated-value coverage, not production recall or F1",
        "scanner_image": SCANNER_IMAGE,
        "suite_sha256": hashlib.sha256(manifest).hexdigest(),
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in (
                "evals/cloudru_cases.py",
                "evals/cloudru_comparison.py",
                "gateway/reference_gateway.py",
                "apps/rag-assistant/secure_rag/cloudru_pii.py",
                "apps/rag-assistant/secure_rag/presidio_pii.py",
                "infra/presidio/recognizers.yaml",
                "infra/presidio/nlp.yaml",
            )
        },
        "summary": {name: aggregate(results, name) for name in ("cloudru", "presidio")},
        "groups": {
            group: {name: aggregate(rows, name) for name in ("cloudru", "presidio")}
            for group, rows in groups.items()
        },
        "residual": {
            "checked_cases": sum(row["after_presidio"]["status"] == "checked" for row in results),
            "detected_cases": sum(row["after_presidio"].get("match_count", 0) > 0 for row in results),
            "case_ids": [row["id"] for row in results if row["after_presidio"].get("match_count", 0) > 0],
            "latency_p50_ms": percentile([row["after_presidio"]["latency_ms"] for row in results], 0.5),
            "latency_p95_ms": percentile([row["after_presidio"]["latency_ms"] for row in results], 0.95),
            "meaning": "Residual detections are observations, not additional redaction or confirmed PII",
        },
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scanner", default="http://cloudru-filter:9080")
    parser.add_argument("--analyzer", default="http://presidio-analyzer:3000")
    parser.add_argument("--anonymizer", default="http://presidio-anonymizer:3000")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--runtime-metadata", type=Path)
    args = parser.parse_args()
    report = evaluate(
        EvaluationScanner(args.scanner),
        PresidioHttpRedactor(
            analyzer_url=args.analyzer,
            anonymizer_url=args.anonymizer,
        ),
    )
    if args.runtime_metadata:
        report["runtime_images"] = json.loads(args.runtime_metadata.read_text())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"summary": report["summary"], "residual": report["residual"]}, indent=2))
    # Expected difficult cases are measured, never waived. Operational failures
    # fail the run; protection rates remain visible rather than becoming a green gate.
    return int(any(row["unavailable"] for row in report["summary"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
