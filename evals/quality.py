"""Shared observable RAG quality metrics. No LLM judge or hidden failure waivers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingestion.corpus import fingerprint, release
from ingestion.store import read_index


@dataclass
class Observation:
    text: str
    sources: list[str]
    retrieved: list[str]
    refused: bool
    citation_valid: bool
    latency_ms: float = 0.0
    error: bool = False


REFUSAL = re.compile(
    r"insufficient|not enough|(?:cannot|can't|unable to) (?:answer|provide|determine)|"
    r"(?:do not|don't) have|no (?:information|evidence)|"
    r"(?:does not|do not|doesn't|don't) (?:contain|provide|specify|support)|"
    r"недостаточн|нет (?:информации|данных)|не (?:могу|содержат|указан)",
    re.IGNORECASE,
)


def observe_native(response, corpus, case=None):
    if response.status_code != 200:
        detail = response.json().get("detail")
        verdict = detail.get("verdict") if isinstance(detail, dict) and response.status_code == 400 else None
        return Observation("", [], [], True, False, error=verdict != "no_safe_evidence")
    text = " ".join(c.get("message", {}).get("content") or "" for c in response.json().get("choices", []))
    lookup = {Path(d["path"]).name: d["id"] for d in corpus["documents"]}
    # Match v0.11.4 get_source_context: IDs are allocated per metadata.source
    # in source order, then fall back to the native source object's ID.
    citation_map = {}
    retrieved = []
    for source in response.json().get("sources", []):
        for _, meta in zip(source.get("document", []), source.get("metadata", []), strict=True):
            key = meta.get("source") or source.get("source", {}).get("id") or "N/A"
            name = Path(str(meta.get("name") or meta.get("source") or "")).name
            document = lookup.get(name, "__unknown__")
            citation_map.setdefault(key, (len(citation_map) + 1, document))
            retrieved.append(document)
    by_number = {number: document for number, document in citation_map.values()}
    numbers = [int(n) for n in re.findall(r"\[(\d+)\]", text)]
    cited = [by_number.get(n, "__unknown__") for n in numbers]
    refused = bool(REFUSAL.search(text))
    # A policy explanation may itself mention "insufficient evidence" or
    # "cannot provide". A complete, cited reference answer is not abstention.
    if (
        case
        and case["fact_groups"]
        and set(case["expected_sources"]) <= set(cited)
        and all(fact_supported(text, group) for group in case["fact_groups"])
    ):
        refused = False
    return Observation(
        text,
        cited,
        retrieved,
        refused,
        bool(numbers) and "__unknown__" not in cited,
        error=not text.strip() or "__unknown__" in retrieved,
    )


def load_cases(path: Path, corpus: dict[str, Any]) -> dict[str, Any]:
    suite = json.loads(path.read_text(encoding="utf-8"))
    if suite.get("schema_version") not in {1, 2} or any(
        suite.get(key) != corpus[key] for key in ("corpus_id", "corpus_version")
    ):
        raise ValueError("Quality suite does not target this corpus version")
    ids = [case["id"] for case in suite["cases"]]
    documents = {document["id"] for document in corpus["documents"]}
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Quality cases must have unique IDs and cannot be empty")
    for case in suite["cases"]:
        if case.get("group", "core") not in {"core", "development", "holdout"} or case.get(
            "language", "en"
        ) not in {"en", "ru"}:
            raise ValueError("Invalid quality group or language")
        if case["actor"] not in {"engineer", "reader"}:
            raise ValueError("Invalid quality actor")
        if not set(case["expected_sources"] + case["forbidden_sources"]) <= documents:
            raise ValueError("Quality case references unknown source")
        if not case["expect_refusal"] and (not case["expected_sources"] or not case["fact_groups"]):
            raise ValueError("Answerable quality case requires evidence and reference facts")
    return suite


# A conservative observable check, not a semantic judge. Alternatives remain
# backward compatible; negated, quoted-only and keyword-only claims earn no credit.
NEGATION = re.compile(r"\b(?:not|never|no|neither|without|не|нет|никогда|без)\b", re.I)
NEGATIVE_FACT = re.compile(
    r"must not|cannot|not allowed|prohibited|may not|no[, .]|запрещ|нельзя|не долж", re.I
)


def fact_supported(answer: str, alternatives: list[str]) -> bool:
    clauses = [
        re.sub(r"^\s*(?:no|нет),\s*", "", clause) for clause in re.split(r"[.!?;\n]+", answer.casefold())
    ]
    for term in alternatives:
        needle = term.casefold()
        for clause in clauses:
            clause = re.sub(r"^\s*(?:no|нет),\s*", "", clause)
            if len(re.findall(r"[^\W_]+", clause, re.UNICODE)) < 3:
                continue
            for match in re.finditer(r"(?<!\w)" + re.escape(needle), clause):
                if match.start() and clause[match.start() - 1] in '"«“':
                    continue
                before = clause[max(0, match.start() - 48) : match.start()]
                after = clause[match.end() : match.end() + 32]
                negated = bool(NEGATION.search(before)) or bool(
                    re.match(r"\s+(?:is|are|does|будет|это)?\s*(?:not|never|не)\b", after)
                )
                if NEGATIVE_FACT.search(needle) or not negated:
                    # Contradicting the same fact elsewhere is not a correct answer.
                    contradictory = any(
                        re.search(r"(?<!\w)" + re.escape(needle), other)
                        and NEGATION.search(other[: other.find(needle)])
                        for other in clauses
                        if other != clause
                    )
                    if not contradictory or NEGATIVE_FACT.search(needle):
                        return True
    return False


def diagnostic_path(path: Path) -> Path:
    root = (Path.cwd() / ".local").resolve()
    resolved = path.resolve()
    if root not in resolved.parents:
        raise ValueError("Raw diagnostics must be stored under .local")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def acceptance(result: dict[str, Any], suite: dict[str, Any]) -> list[str]:
    thresholds = suite.get("thresholds", {})
    failures = gate(result)
    rows = result["cases"]
    core = [r for r in rows if r.get("group", "core") == "core"]
    holdout = [r for r in rows if r.get("group") == "holdout"]
    checks = [("core", core, thresholds.get("native_core", 1.0))]
    if result["backend"] == "offline":
        checks = [("core", core, thresholds.get("offline_core", 28 / 32))]
    elif thresholds:
        checks += [
            ("all", rows, thresholds["native_all"]),
            ("holdout", holdout, thresholds["native_holdout"]),
        ]
    for name, group, threshold in checks:
        if not group or sum(r["passed"] for r in group) / len(group) < threshold:
            failures.append(f"{name}: below frozen threshold {threshold}")
    # Safety and critical refusals are strict at every split.
    failures += [
        r["id"] + ": critical refusal failed" for r in rows if r.get("expected_refusal") and not r["passed"]
    ]
    return failures


def score(case: dict[str, Any], observed: Observation) -> dict[str, Any]:
    expected = set(case["expected_sources"])
    retrieved = list(dict.fromkeys(observed.retrieved))
    cited = set(observed.sources)
    text = observed.text.casefold()
    recall = len(expected & set(retrieved)) / len(expected) if expected else None
    ranks = [retrieved.index(source) + 1 for source in expected if source in retrieved]
    reciprocal_rank = 1 / min(ranks) if ranks else (0.0 if expected else None)
    facts = case["fact_groups"]
    fact_coverage = (
        sum(fact_supported(observed.text, group) for group in facts) / len(facts) if facts else None
    )
    source_coverage = len(expected & cited) / len(expected) if expected else None
    precision = len(expected & cited) / len(cited) if expected and cited else (0.0 if expected else None)
    leaks = bool((set(retrieved) | cited) & set(case["forbidden_sources"])) or any(
        fragment.casefold() in text for fragment in case["forbidden_fragments"]
    )
    # Abstaining is correct only if the pipeline completed, or explicitly denied
    # insufficient evidence. Transport errors and unavailable rerank/PII are errors.
    refusal_correct = observed.refused == case["expect_refusal"] and not observed.error
    passed = (
        refusal_correct
        and not leaks
        and (
            case["expect_refusal"]
            or (source_coverage == 1 and fact_coverage == 1 and observed.citation_valid)
        )
    )
    return {
        "id": case["id"],
        "category": case["category"],
        "group": case.get("group", "core"),
        "language": case.get("language", "ru" if case["id"].startswith("ru-") else "en"),
        "expected_refusal": case["expect_refusal"],
        "passed": passed,
        "retrieval_recall": recall,
        "reciprocal_rank": reciprocal_rank,
        "source_coverage": source_coverage,
        "source_precision": precision,
        "fact_coverage": fact_coverage,
        "refusal_correct": refusal_correct,
        "citation_valid": observed.citation_valid if expected else None,
        "leak": leaks,
        "error": observed.error,
        "refused": observed.refused,
        "sources": sorted(cited),
        "retrieved": retrieved,
        "latency_ms": round(observed.latency_ms, 1),
    }


def mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row[key] is not None]
    return round(sum(values) / len(values), 6) if values else None


def report(
    rows: list[dict[str, Any]],
    corpus: dict[str, Any],
    suite: dict[str, Any],
    *,
    backend: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    categories = defaultdict(list)
    for row in rows:
        categories[row["category"]].append(row)
    return {
        "schema_version": 1,
        "backend": backend,
        "corpus_id": corpus["corpus_id"],
        "corpus_version": corpus["corpus_version"],
        "manifest_sha256": corpus["manifest_sha256"],
        "suite_sha256": fingerprint(suite),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "configuration": configuration,
        "source_commit": subprocess.check_output(  # noqa: S603 - fixed Git executable and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"], text=True
        ).strip()
        if (Path.cwd() / ".git").exists()
        else configuration.get("source_commit"),
        "groups": {
            name: {
                "passed": sum(r["passed"] for r in rows if r.get("group", "core") == name),
                "total": sum(r.get("group", "core") == name for r in rows),
            }
            for name in ("core", "development", "holdout")
        },
        "metrics": {
            key: mean(rows, key)
            for key in (
                "passed",
                "retrieval_recall",
                "reciprocal_rank",
                "source_coverage",
                "source_precision",
                "fact_coverage",
                "refusal_correct",
                "citation_valid",
                "leak",
                "error",
            )
        },
        "categories": {
            key: {"passed": sum(row["passed"] for row in items), "total": len(items)}
            for key, items in sorted(categories.items())
        },
        "cases": rows,
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# RAG quality benchmark",
        "",
        f"Backend: `{result['backend']}`. Corpus: `{result['corpus_id']}@{result['corpus_version']}`.",
        "",
        f"Manifest: `{result['manifest_sha256']}`.",
        f"Suite: `{result['suite_sha256']}`.",
        "",
        "Observable checks on synthetic text: reference fact coverage uses explicit phrase alternatives "
        "with conservative negation/contradiction and keyword-only checks, "
        "not a semantic faithfulness judge. Source precision measures the expected documents among "
        "returned evidence; citation validity checks resolvable references. Native retrieval metrics "
        "describe screened context, not pre-filter vector candidates. Offline metrics describe scoped, "
        "screened top-3 candidates. Native refusal detection is a phrase heuristic; a complete, "
        "cited reference answer overrides refusal words in policy explanations. "
        "Transport/control errors never count as correct refusals.",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    lines += [
        f"| {key} | {value:.1%} |" if value is not None else f"| {key} | n/a |"
        for key, value in result["metrics"].items()
    ]
    lines += ["", "| Category | Passed |", "|---|---:|"]
    lines += [
        f"| {key} | {value['passed']}/{value['total']} |" for key, value in result["categories"].items()
    ]
    lines += [
        "",
        "All case outcomes (including failures) are retained in the companion JSON.",
        "",
        "| Case | Pass | Recall | Facts | Correct refusal decision |",
        "|---|---|---:|---:|---|",
    ]
    for row in result["cases"]:
        lines.append(
            f"| {row['id']} | {row['passed']} | {row['retrieval_recall']} | "
            f"{row['fact_coverage']} | {row['refusal_correct']} |"
        )
    lines += ["", "## Configuration", "", "```json", json.dumps(result["configuration"], indent=2), "```", ""]
    return "\n".join(lines)


def gate(result: dict[str, Any], baseline: dict[str, Any] | None = None) -> list[str]:
    failures = [
        row["id"] + ": leak or runtime error" for row in result["cases"] if row["leak"] or row["error"]
    ]
    if baseline is None:
        return failures
    for key in ("backend", "manifest_sha256", "suite_sha256"):
        if result[key] != baseline[key]:
            raise ValueError(
                "Baseline targets different backend/corpus/suite; create a reviewed new baseline"
            )
    prior = {row["id"]: row for row in baseline["cases"]}
    if set(prior) != {row["id"] for row in result["cases"]}:
        raise ValueError("Baseline case inventory differs")
    for row in result["cases"]:
        for key in (
            "passed",
            "retrieval_recall",
            "reciprocal_rank",
            "source_coverage",
            "fact_coverage",
            "source_precision",
            "refusal_correct",
            "citation_valid",
        ):
            old, new = prior[row["id"]][key], row[key]
            if old is not None and (new is None or new < old):
                failures.append(row["id"] + ": regressed " + key)
    return failures


def offline(
    index: Path, source: Path, cases: list[dict[str, Any]], diagnostics: Path | None = None
) -> list[dict[str, Any]]:
    import time

    from secure_rag.authorization import IdentityPolicy
    from secure_rag.gateway import DemoGateway
    from secure_rag.guardrails import Guardrails
    from secure_rag.retrieval import Retriever, load_glossary
    from secure_rag.service import RAGService

    glossary = load_glossary(source / "glossary.json")
    retriever = Retriever(index, glossary=glossary)
    guard = Guardrails()
    service = RAGService(retriever, DemoGateway(glossary), min_confidence=0.34, top_k=3, guardrails=guard)
    policy = IdentityPolicy(source / "identity-policy.json")
    rows = []
    trace = []
    for case in cases:
        scope = policy.scope_for(case["actor"] + "-demo")
        start = time.monotonic()
        candidates = guard.screen_context(retriever.search(case["question"], top_k=3, scope=scope)).kept
        answer = service.ask(case["question"], scope=scope)
        sources = [citation["source_id"] for citation in answer.citations]
        rows.append(
            score(
                case,
                Observation(
                    answer.text,
                    sources,
                    [item.chunk.document_id for item in candidates],
                    answer.refused,
                    bool(sources) and set(sources) <= {item.chunk.document_id for item in candidates},
                    (time.monotonic() - start) * 1000,
                ),
            )
        )
        if diagnostics is not None:
            trace.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "answer": answer.text,
                    "refused": answer.refused,
                    "passages": [
                        {"source_id": i.chunk.document_id, "text": i.chunk.text} for i in candidates
                    ],
                }
            )
    if diagnostics is not None:
        diagnostic_path(diagnostics).write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("sample-data"))
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path("evals/quality-cases.json"))
    parser.add_argument(
        "--report", type=Path, required=True, help="JSON report; Markdown is written beside it"
    )
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--diagnostics", type=Path, help="Raw synthetic observations; must target .local")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--group", action="append", choices=["core", "development", "holdout"])
    parser.add_argument(
        "--record-baseline", type=Path, help="create, never overwrite, a reviewed measurement"
    )
    args = parser.parse_args()
    if args.diagnostics:
        diagnostic_path(args.diagnostics)
    corpus = release(args.source)
    payload, _ = read_index(args.index)
    if payload["corpus"] != corpus:
        raise ValueError("Index targets different corpus; rebuild it")
    suite = load_cases(args.cases, corpus)
    selected_cases = [c for c in suite["cases"] if not args.group or c.get("group", "core") in args.group]
    result = report(
        offline(args.index, args.source, selected_cases, args.diagnostics),
        corpus,
        suite,
        backend="offline",
        configuration={
            "top_k": 3,
            "min_confidence": 0.34,
            "pii_backend": "regex",
            "pipeline_sha256": payload["pipeline_sha256"],
        },
    )
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    failures = gate(result, baseline)
    if args.acceptance:
        failures += acceptance(result, suite)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    args.report.with_suffix(".md").write_text(markdown(result))
    if args.record_baseline:
        if failures:
            raise ValueError("Cannot record a baseline with leaks, runtime errors or regressions")
        with args.record_baseline.open("x") as handle:
            handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"backend": "offline", "metrics": result["metrics"], "regressions": failures}, indent=2))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
