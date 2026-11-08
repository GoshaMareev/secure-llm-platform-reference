"""Synthetic labeled decision benchmark; live calls require --live explicitly."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from secure_rag.decision_guardrails import (
    BLOCK_THRESHOLD,
    POLICY_SHA256,
    POLICY_VERSION,
    DecisionClient,
    DecisionUnavailable,
    digest,
    is_risk,
    questions_for,
)
from secure_rag.guardrails import (
    CONTEXT_ONLY_RULES,
    EXFILTRATION_RULES,
    INJECTION_RULES,
    RegexPiiRedactor,
    _matches,
)

from ingestion.corpus import release

ROOT = Path(__file__).resolve().parents[1]


def load_cases(path):
    raw = json.loads(path.read_text())
    cases = raw["cases"]
    seen = set()
    for case in cases:
        if case["id"] in seen or case["split"] not in {"development", "holdout"}:
            raise ValueError("Invalid decision case ID or split")
        seen.add(case["id"])
        questions = questions_for(case["stage"], case["state"])
        if not case["labels"] or set(case["labels"]) - set(questions):
            raise ValueError("Labels must reference evaluated questions")
        if any(not isinstance(v, bool) for v in case["labels"].values()):
            raise ValueError("Labels must be binary")
    return raw


def baseline(case, question):
    state = case["state"]
    if question == "input_override":
        return bool(
            _matches(state["query"], tuple(r for r in INJECTION_RULES if r.name != "reveal-system-prompt"))
        )
    if question == "input_secret_request":
        return bool(
            _matches(state["query"], tuple(r for r in INJECTION_RULES if r.name == "reveal-system-prompt"))
        )
    if question.startswith("untrusted_"):
        index = int(question.split("_")[1])
        return bool(
            _matches(state.get("untrusted_inputs", [])[index], (*INJECTION_RULES, *EXFILTRATION_RULES))
        )
    if question.endswith("_attack"):
        index = int(question.split("_")[1])
        return bool(
            _matches(state["passages"][index], (*INJECTION_RULES, *EXFILTRATION_RULES, *CONTEXT_ONLY_RULES))
        )
    if question == "output_unsafe":
        return bool(_matches(state["answer"], (*INJECTION_RULES, *EXFILTRATION_RULES)))
    # The deterministic layer has no factual-support judgment.
    return False


def metrics(rows):
    available = [row for row in rows if row["score"] is not None]
    tp = sum(row["label"] and row["score"] >= BLOCK_THRESHOLD for row in available)
    fn = sum(row["label"] and row["score"] < BLOCK_THRESHOLD for row in available)
    fp = sum(not row["label"] and row["score"] >= BLOCK_THRESHOLD for row in available)
    tn = len(available) - tp - fn - fp
    return {
        "labeled_judgments": len(rows),
        "available": len(available),
        "unavailable": len(rows) - len(available),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "false_negative_rate": round(fn / (tp + fn), 4) if tp + fn else None,
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
        "accuracy_on_available": round((tp + tn) / len(available), 4) if available else None,
        "brier_score": round(sum((r["score"] - r["label"]) ** 2 for r in available) / len(available), 4)
        if available
        else None,
    }


def evaluate(client, data, corpus):
    rows, calls = [], []
    pii = RegexPiiRedactor()  # Fixtures are synthetic; runtime uses mandatory Presidio.
    for case in data["cases"]:
        state = {
            "untrusted_inputs": [pii.redact(text)[0] for text in case["state"].get("untrusted_inputs", [])],
            "query": pii.redact(case["state"]["query"])[0],
            "passages": [pii.redact(text)[0] for text in case["state"]["passages"]],
        }
        if "answer" in case["state"]:
            state["answer"] = pii.redact(case["state"]["answer"])[0]
        try:
            result = client.evaluate(case["stage"], state)
            call = {"case_id": case["id"], **result.event(case["stage"])}
            scores = result.scores
        except DecisionUnavailable as error:
            call = {"case_id": case["id"], "status": "unavailable", "reason": str(error)}
            scores = {}
        call.update(language=case["language"], task=case["stage"], split=case["split"])
        calls.append(call)
        for question, label in case["labels"].items():
            rows.append(
                {
                    "case_id": case["id"],
                    "split": case["split"],
                    "language": case["language"],
                    "question": question,
                    "label": label,
                    "score": scores.get(question),
                    "baseline": baseline(case, question) if is_risk(question) else None,
                }
            )
    groups = defaultdict(list)
    for row in rows:
        if is_risk(row["question"]):
            groups[f"risk/{row['split']}/{row['language']}"].append(row)
            groups[f"risk/{row['split']}/all"].append(row)
        groups[f"question/{row['question']}"].append(row)
    baseline_groups = {
        key: metrics([{**row, "score": float(row["baseline"])} for row in group])
        for key, group in groups.items()
        if key.startswith("risk/")
    }
    latencies = sorted(call["latency_ms"] for call in calls if call["status"] == "ok")
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": digest(data),
        "policy_version": POLICY_VERSION,
        "policy_sha256": POLICY_SHA256,
        "corpus_version": corpus["corpus_version"],
        "manifest_sha256": corpus["manifest_sha256"],
        "provider": client.provider,
        "requested_model": client.model,
        "resolved_models": sorted({c["model"] for c in calls if c["status"] == "ok"}),
        "mode": "shadow",
        "threshold": BLOCK_THRESHOLD,
        "case_count": len(calls),
        "unavailable_calls": sum(c["status"] != "ok" for c in calls),
        "p95_latency_ms": latencies[max(0, (len(latencies) * 95 + 99) // 100 - 1)] if latencies else None,
        "reported_cost_usd": round(sum(c.get("cost_usd") or 0 for c in calls), 8),
        "cost_reporting_complete": all(c.get("cost_usd") is not None for c in calls),
        "call_metrics": {
            key: {
                "calls": len(group),
                "unavailable": sum(c["status"] != "ok" for c in group),
                "reported_cost_usd": round(sum(c.get("cost_usd") or 0 for c in group), 8),
                "p95_latency_ms": sorted(c["latency_ms"] for c in group if c["status"] == "ok")[
                    max(0, (sum(c["status"] == "ok" for c in group) * 95 + 99) // 100 - 1)
                ]
                if any(c["status"] == "ok" for c in group)
                else None,
            }
            for key in sorted({c["language"] + "/" + c["task"] for c in calls})
            for group in [[c for c in calls if c["language"] + "/" + c["task"] == key]]
        },
        "metrics": {key: metrics(group) for key, group in sorted(groups.items())},
        "deterministic_baseline": baseline_groups,
        "judgments": rows,
        "calls": calls,
        "limitations": [
            "Small synthetic benchmark; fixed threshold 0.80 is not calibrated for production.",
            "Development and holdout are separate; do not retune policy using holdout labels.",
            "Unavailable judgments are excluded from accuracy and reported; they are not approvals.",
            "Passages are fixtures, not retrieval results; corpus manifest binds the project release.",
            "Only text decisions evaluated, including cleaned OCR/STT fixtures as untrusted inputs; "
            "actual media privacy has its own independent benchmark.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "evals/decision-cases.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--validate-only", action="store_true")
    parser.add_argument("--provider", choices=["openrouter", "cloudflare"], default="openrouter")
    parser.add_argument("--model", default="typesafe/jev-1.13")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--account", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    parser.add_argument("--report", type=Path, default=ROOT / ".local/decision-evaluation.json")
    args = parser.parse_args()
    data = load_cases(args.cases)
    if args.validate_only:
        print(f"Validated {len(data['cases'])} synthetic decision cases; no inference.")
        return
    key_env = "OPENROUTER_API_KEY" if args.provider == "openrouter" else "CLOUDFLARE_AUTH_TOKEN"
    key = args.key_file.read_text().strip() if args.key_file else os.environ.get(key_env, "")
    client = DecisionClient(key, provider=args.provider, model=args.model, account=args.account)
    report = evaluate(client, data, release(ROOT / "sample-data"))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps({k: report[k] for k in ("case_count", "unavailable_calls", "reported_cost_usd")}, indent=2)
    )
    if report["unavailable_calls"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
