"""Bounded hosted shadow benchmark with preflight and per-call budget checks."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/rag-assistant")]
from provider_budget import remaining  # noqa: E402
from secure_rag.decision_guardrails import DecisionClient, DecisionUnavailable  # noqa: E402

from evals.decisions import evaluate, load_cases  # noqa: E402
from ingestion.corpus import release  # noqa: E402


class BudgetClient(DecisionClient):
    def __init__(self, key_file):
        self.key_file = key_file
        self.initial, balance = remaining(key_file)
        if balance < 1:
            raise ValueError("Insufficient reserved run budget")
        super().__init__(key_file.read_text().strip())

    def evaluate(self, stage, state):
        try:
            used, balance = remaining(self.key_file)
        except Exception:
            raise DecisionUnavailable("budget_unavailable") from None
        if used - self.initial >= 0.95 or balance < 0.05:
            raise DecisionUnavailable("budget_limit")
        return super().evaluate(stage, state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if (
        not args.live
        or (ROOT / ".local").resolve() not in args.report.resolve().parents
        or args.report.exists()
    ):
        raise SystemExit("Explicit hosted run and fresh private report required")
    client = BudgetClient(ROOT / ".local/openrouter/api-key")
    path = ROOT / "evals/decision-expanded-v2.json"
    result = evaluate(client, load_cases(path), release(ROOT / "sample-data"))
    result["source_commit"] = subprocess.check_output(  # noqa: S603 - fixed local Git query
        [shutil.which("git"), "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()  # noqa: S603,S607 - fixed revision query
    result["suite_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    used, _ = remaining(client.key_file)
    result["budget"] = {
        "actual_run_cost_usd": round(used - client.initial, 8),
        "total_used_usd": used,
        "run_limit_usd": 1,
    }
    if used - client.initial > 1:
        raise RuntimeError("Run budget exceeded")
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["case_count", "unavailable_calls", "p95_latency_ms", "budget"]}))
