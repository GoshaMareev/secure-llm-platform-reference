"""Real OCR/STT/PII against frozen fixtures; public output contains measurements only."""

import argparse
import base64
import hashlib
import json
import time
from difflib import SequenceMatcher
from pathlib import Path

from secure_rag.media_guardrails import LocalMediaInspector, MediaRejected, normalize_spoken
from secure_rag.presidio_pii import PresidioHttpRedactor


def verify(suite_path, fixtures, report_path):
    suite = json.loads(suite_path.read_text())
    pii = PresidioHttpRedactor()
    inspector = LocalMediaInspector(pii)
    rows = []
    traces = []
    for case in suite["cases"]:
        path = fixtures / (case["id"] + (".png" if case["kind"] == "image" else ".wav"))
        raw = path.read_bytes()
        encoded = base64.b64encode(raw).decode()
        part = (
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}}
            if case["kind"] == "image"
            else {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}}
        )
        start = time.monotonic()
        observed = {}
        allowed = False
        redacted = []
        text = ""
        verdict = "error"
        original = inspector._inspect

        def capture(*args, original=original):
            nonlocal observed
            observed = original(*args)
            return observed

        inspector._inspect = capture
        try:
            checked = inspector.check(part)
            allowed = True
            verdict = checked.verdict
            redacted = list(checked.redacted_kinds)
            text = checked.untrusted_text
        except MediaRejected as error:
            verdict = str(error)
        finally:
            inspector._inspect = original
        sensitive = case["category"] in {"pii", "credentials"}
        unresolved = allowed and sensitive and (case["kind"] == "image" or not redacted)
        # No raw audio is ever forwarded; sensitive-image allowance is a leak
        # even when OCR missed the value. Audio allowance needs explicit cleaning.
        privacy_pass = not unresolved
        benign_pass = allowed if case["category"] == "benign" else None
        expected = case["expected"]
        classification_pass = (
            allowed if expected == "allow" else not allowed if expected == "block" else privacy_pass
        )
        extracted = observed.get("text", "")
        recognition = (
            SequenceMatcher(
                None, normalize_spoken(case["text"]).casefold(), normalize_spoken(extracted).casefold()
            ).ratio()
            if extracted
            else 0.0
        )
        rows.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "language": case["language"],
                "category": case["category"],
                "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                "allowed": allowed,
                "verdict": verdict,
                "privacy_pass": privacy_pass,
                "benign_pass": benign_pass,
                "classification_pass": classification_pass,
                "recognition_similarity": round(recognition, 4),
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        )
        traces.append(
            {
                "id": case["id"],
                "expected_text": case["text"],
                "extracted_text": extracted,
                "cleaned_text": text,
                "redacted_kinds": redacted,
            }
        )
        print(case["id"] + ": " + verdict, flush=True)
    benign = [r for r in rows if r["benign_pass"] is not None]
    benign_rate = sum(r["benign_pass"] for r in benign) / len(benign)
    result = {
        "schema_version": 1,
        "suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "configuration": {
            "physical_manifest": json.loads((report_path.parent / "physical-manifest.json").read_text()),
            "ru_media": "candidate verification only",
            "pii": "mandatory en+ru union",
        },
        "metrics": {
            "cases": len(rows),
            "potential_sensitive_escapes": sum(not r["privacy_pass"] for r in rows),
            "benign_pass_rate": benign_rate,
            "classification_passed": sum(r["classification_pass"] for r in rows),
            "mean_recognition_similarity": sum(r["recognition_similarity"] for r in rows) / len(rows),
        },
        "accepted": all(r["privacy_pass"] for r in rows)
        and all(not r["allowed"] for r in rows if r["category"] == "injection")
        and benign_rate >= suite["thresholds"]["benign_pass_rate"],
        "cases": rows,
    }
    report_path.write_text(json.dumps(result, indent=2) + "\n")
    report_path.with_suffix(".private-trace.json").write_text(
        json.dumps(traces, ensure_ascii=False, indent=2) + "\n"
    )
    return result["accepted"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if verify(args.suite, args.fixtures, args.report) else 1)
