from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "rag-assistant")]

from secure_rag.service import REFUSAL, Answer  # noqa: E402

from evals.run import CaseResult, evaluate_case  # noqa: E402


class EvaluationGateTests(unittest.TestCase):
    def test_known_quality_failure_does_not_waive_new_leak_or_control_failure(self):
        result = CaseResult(
            "known",
            "grounded",
            False,
            ["missing source access-control"],
            known_limitation="retrieval",
            allowed_failures=("missing source access-control",),
        )
        self.assertFalse(result.gating_failure)
        for failure in (
            "answer leaks 'private'",
            "blocked=True, expected False",
            "missing source new-source",
        ):
            result.failures.append(failure)
            self.assertTrue(result.gating_failure)
            result.failures.pop()
        result.allowed_failures = ("answer leaks 'private'",)
        result.failures = ["answer leaks 'private'"]
        self.assertTrue(result.gating_failure)

    def test_safe_refusal_without_verdict_is_control_failure_not_policy_breach(self):
        class SafeRefusingService:
            def ask(self, *args, **kwargs):
                return Answer(REFUSAL, 0.0, True, ())

        cases = [
            json.loads(line) for line in Path("evals/cases.jsonl").read_text().splitlines() if line.strip()
        ]
        case = next(c for c in cases if c["id"] == "inject-ignore")
        result = evaluate_case(SafeRefusingService(), case)
        self.assertFalse(result.breached)
        self.assertTrue(result.gating_failure)
