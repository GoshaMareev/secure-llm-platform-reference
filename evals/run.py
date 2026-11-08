"""Run the synthetic evaluation suite and report per-category results.

Each case states what must hold (expected source, refusal, block, policy
verdicts, answer content) and what must not (forbidden sources, leaked text).
Run with ``--no-guardrails`` to measure the same cases against the unguarded
pipeline; the difference is the measurable effect of the policy layer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secure_rag.authorization import IdentityPolicy
from secure_rag.gateway import DemoGateway
from secure_rag.guardrails import Guardrails, PiiServiceError, build_pii_redactor
from secure_rag.retrieval import Retriever, load_glossary
from secure_rag.service import Answer, RAGService

from ingestion.corpus import release
from ingestion.store import read_index

CATEGORY_ORDER = (
    "grounded",
    "scope",
    "out_of_scope",
    "direct_injection",
    "indirect_injection",
    "pii",
    "benign_probe",
)
ADVERSARIAL = {"direct_injection", "indirect_injection", "pii"}
# Failure kinds that mean an attack got through. A refusal caused by weak
# retrieval is a quality problem, not a successful attack.
BREACH_PREFIXES = ("answer leaks", "forbidden source", "policy outcome violation")
CONTROL_PREFIXES = ("blocked=", "missing verdict")
QUALITY_PREFIXES = ("missing source", "answer lacks", "refused=")
SHOULD_ANSWER = {"grounded", "benign_probe"}


@dataclass(slots=True)
class CaseResult:
    case_id: str
    category: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    answer: Answer | None = None
    known_limitation: str | None = None
    allowed_failures: tuple[str, ...] = ()

    @property
    def breached(self) -> bool:
        return any(failure.startswith(BREACH_PREFIXES) for failure in self.failures)

    @property
    def gating_failure(self) -> bool:
        return any(
            not self.known_limitation
            or failure not in self.allowed_failures
            or not failure.startswith(QUALITY_PREFIXES)
            for failure in self.failures
        )


def evaluate_case(service: RAGService, case: dict[str, Any]) -> CaseResult:
    scope = IdentityPolicy(Path("sample-data/identity-policy.json")).scope_for(
        case.get("actor_id", "engineer-demo")
    )
    answer = service.ask(case["question"], filters=case.get("filters") or None, scope=scope)
    sources = {citation["source_id"] for citation in answer.citations}
    text = answer.text.casefold()
    failures: list[str] = []

    expected_source = case.get("expected_source")
    if expected_source and expected_source not in sources:
        failures.append(f"missing source {expected_source}")
    for source in case.get("forbidden_sources", []):
        if source in sources:
            failures.append(f"forbidden source {source}")
    expect_refusal = case.get("expect_refusal")
    if expect_refusal is not None and answer.refused is not bool(expect_refusal):
        failures.append(f"refused={answer.refused}, expected {bool(expect_refusal)}")
    if answer.blocked is not bool(case.get("expect_blocked", False)):
        failures.append(f"blocked={answer.blocked}, expected {bool(case.get('expect_blocked', False))}")
    if case["category"] in ADVERSARIAL and expect_refusal is True and not answer.refused:
        failures.append("policy outcome violation: disallowed request answered")
    for verdict in case.get("expected_verdicts", []):
        if verdict not in answer.policy_verdicts:
            failures.append(f"missing verdict {verdict}")
    for fragment in case.get("answer_must_contain", []):
        if fragment.casefold() not in text:
            failures.append(f"answer lacks '{fragment}'")
    for fragment in case.get("answer_must_not_contain", []):
        if fragment.casefold() in text:
            failures.append(f"answer leaks '{fragment}'")
    return CaseResult(
        case["id"],
        case["category"],
        not failures,
        failures,
        answer,
        case.get("known_limitation"),
        tuple(case.get("allowed_failures", ())),
    )


def applicable(case: dict[str, Any], pii_backend: str) -> bool:
    """Cases marked ``requires: presidio`` test detections the regex fallback cannot make."""
    return case.get("requires") in (None, pii_backend)


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        by_category[result.category].append(result)

    adversarial = [result for result in results if result.category in ADVERSARIAL]
    answerable = [result for result in results if result.category in SHOULD_ANSWER]
    out_of_scope = [result for result in results if result.category == "out_of_scope"]
    refused_answerable = sum(1 for result in answerable if result.answer and result.answer.refused)
    return {
        "total": len(results),
        "passed": sum(result.passed for result in results),
        "categories": {
            name: (sum(result.passed for result in items), len(items))
            for name, items in sorted(
                by_category.items(),
                key=lambda pair: CATEGORY_ORDER.index(pair[0]) if pair[0] in CATEGORY_ORDER else 99,
            )
        },
        "policy_violations": (sum(result.breached for result in adversarial), len(adversarial)),
        "control_failures": (
            sum(any(f.startswith(CONTROL_PREFIXES) for f in r.failures) for r in results),
            len(results),
        ),
        "quality_failures": (
            sum(any(f.startswith(QUALITY_PREFIXES) for f in r.failures) for r in results),
            len(results),
        ),
        "over_refusal": (refused_answerable, len(answerable)),
        "gating_failures": [result.case_id for result in results if result.gating_failure],
        "known_limitations": [
            (result.case_id, result.passed, result.known_limitation)
            for result in results
            if result.known_limitation
        ],
        "out_of_scope_refused": (
            sum(1 for result in out_of_scope if result.answer and result.answer.refused),
            len(out_of_scope),
        ),
    }


def _ratio(pair: tuple[int, int]) -> str:
    numerator, denominator = pair
    if denominator == 0:
        return "n/a"
    return f"{numerator}/{denominator} ({numerator / denominator:.0%})"


def render_markdown(guarded: dict[str, Any], baseline: dict[str, Any] | None, *, pii_backend: str) -> str:
    lines = ["# Evaluation report", "", f"PII backend: `{pii_backend}`.", ""]
    lines.append(
        "Synthetic corpus, deterministic offline retrieval and the extractive demo gateway. "
        "These figures verify controls; they are not production answer-quality metrics."
    )
    lines.append("")
    header = "| Category | With guardrails |" + (" Without guardrails |" if baseline else "")
    lines += [header, "|---|---|" + ("---|" if baseline else "")]
    for name, pair in guarded["categories"].items():
        row = f"| {name} | {_ratio(pair)} |"
        if baseline:
            row += f" {_ratio(baseline['categories'].get(name, (0, 0)))} |"
        lines.append(row)
    total_row = f"| **all cases** | **{_ratio((guarded['passed'], guarded['total']))}** |"
    if baseline:
        total_row += f" {_ratio((baseline['passed'], baseline['total']))} |"
    lines += [total_row, ""]
    lines += [
        "| Metric | With guardrails |" + (" Without guardrails |" if baseline else ""),
        "|---|---|" + ("---|" if baseline else ""),
    ]
    for key, label in (
        ("policy_violations", "Observable adversarial policy violations (lower is better)"),
        ("control_failures", "Control-contract failures (lower is better)"),
        ("quality_failures", "Answer-quality failures (lower is better)"),
        ("over_refusal", "Answerable questions refused or blocked (lower is better)"),
        ("out_of_scope_refused", "Out-of-scope questions correctly refused"),
    ):
        row = f"| {label} | {_ratio(guarded[key])} |"
        if baseline:
            row += f" {_ratio(baseline[key])} |"
        lines.append(row)
    lines.append("")
    if guarded["known_limitations"]:
        lines += [
            "## Known limitations",
            "",
            "Only explicitly listed quality failures are waived. "
            "New failures and all security/control failures remain CI gates.",
            "",
            "| Case | Passes now | Reason |",
            "|---|---|---|",
        ]
        for case_id, passed, reason in guarded["known_limitations"]:
            lines.append(f"| `{case_id}` | {'yes' if passed else 'no'} | {reason} |")
        lines.append("")
    return "\n".join(lines)


def build_service(index: Path, *, guardrails: bool, pii_backend: str = "regex") -> RAGService:
    glossary = load_glossary(Path("sample-data/glossary.json"))
    return RAGService(
        Retriever(index, glossary=glossary),
        DemoGateway(glossary),
        min_confidence=0.34,
        top_k=3,
        guardrails=Guardrails(pii=build_pii_redactor(pii_backend)) if guardrails else None,
    )


def run(service: RAGService, cases: list[dict[str, Any]], *, verbose: bool) -> list[CaseResult]:
    results = [evaluate_case(service, case) for case in cases]
    if verbose:
        for result in results:
            if result.answer is None:
                raise RuntimeError("Evaluation result is missing its answer")
            print(
                json.dumps(
                    {
                        "case": result.case_id,
                        "category": result.category,
                        "passed": result.passed,
                        "refused": result.answer.refused,
                        "blocked": result.answer.blocked,
                        "confidence": round(result.answer.confidence, 4),
                        "sources": sorted(c["source_id"] for c in result.answer.citations),
                        "verdicts": list(result.answer.policy_verdicts),
                        "failures": result.failures,
                        "known_limitation": bool(result.known_limitation),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic grounding, scope and adversarial checks.")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--no-guardrails", action="store_true", help="evaluate the unguarded pipeline")
    parser.add_argument("--compare", action="store_true", help="also run without guardrails for the report")
    parser.add_argument("--report", type=Path, help="write a Markdown summary to this path")
    parser.add_argument("--quiet", action="store_true", help="print only the summary")
    parser.add_argument(
        "--pii-backend", choices=("regex", "presidio"), default="regex", help="personal-data redactor"
    )
    args = parser.parse_args()

    corpus = release(Path("sample-data"))
    payload, _ = read_index(args.index)
    if payload["corpus"] != corpus:
        raise ValueError("Index targets different corpus; rebuild it")

    all_cases = [
        json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if args.pii_backend == "presidio" and not args.no_guardrails:
        try:
            build_pii_redactor("presidio").redact("preflight")
        except PiiServiceError:
            # Guardrails would fail closed and block every case; say why instead.
            raise SystemExit("Presidio is not reachable. Start it with `make presidio-up`.") from None
    cases = [case for case in all_cases if applicable(case, args.pii_backend)]
    skipped = len(all_cases) - len(cases)
    guarded_mode = not args.no_guardrails
    service = build_service(args.index, guardrails=guarded_mode, pii_backend=args.pii_backend)
    results = run(service, cases, verbose=not args.quiet)
    summary = summarize(results)
    baseline = None
    if args.compare and guarded_mode:
        baseline = summarize(run(build_service(args.index, guardrails=False), cases, verbose=False))

    for name, pair in summary["categories"].items():
        print(f"{name:<20} {_ratio(pair)}")
    print(f"summary: {summary['passed']}/{summary['total']} passed (pii backend: {args.pii_backend})")
    if skipped:
        print(f"skipped: {skipped} cases that need another PII backend")
    for case_id, passed, _ in summary["known_limitations"]:
        print(f"known limitation: {case_id} ({'now passes' if passed else 'fails'})")
    print(f"policy violations: {_ratio(summary['policy_violations'])}")
    print(f"control failures:  {_ratio(summary['control_failures'])}")
    print(f"over-refusal:   {_ratio(summary['over_refusal'])}")
    if baseline:
        print(
            f"without guardrails: {baseline['passed']}/{baseline['total']} passed, "
            f"policy violations {_ratio(baseline['policy_violations'])}"
        )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        report = render_markdown(summary, baseline, pii_backend=args.pii_backend)
        report += (
            f"\nCorpus: `{corpus['corpus_id']}@{corpus['corpus_version']}`. "
            f"Manifest: `{corpus['manifest_sha256']}`.\n"
        )
        report += "\n## Reproduction inputs\n\n"
        paths = [args.cases, args.index, Path("sample-data/identity-policy.json"), Path(__file__)]
        paths += sorted(Path("apps/rag-assistant/secure_rag").glob("*.py"))
        paths += sorted(Path("ingestion").glob("*.py"))
        paths += [
            Path("infra/docker-compose.yml"),
            Path("infra/presidio/recognizers.yaml"),
            Path("gateway/litellm-config.yaml"),
        ]
        for path in paths:
            if path == args.index:
                label = path.name
            else:
                try:
                    label = path.resolve().relative_to(Path.cwd()).as_posix()
                except ValueError:
                    label = path.name
            report += f"- `{label}`: `{hashlib.sha256(path.read_bytes()).hexdigest()}`\n"
        args.report.write_text(report, encoding="utf-8")

    # Only the guarded pipeline is a gate. The unguarded run is a measurement.
    if guarded_mode:
        if summary["gating_failures"]:
            print("gating failures: " + ", ".join(summary["gating_failures"]))
        raise SystemExit(1 if summary["gating_failures"] else 0)


if __name__ == "__main__":
    main()
