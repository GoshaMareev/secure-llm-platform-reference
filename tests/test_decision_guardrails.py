"""Protocol validation and shadow-policy boundaries, without hosted calls."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/rag-assistant"))

from secure_rag.decision_guardrails import (  # noqa: E402
    JEV_RESOLVED_MODEL,
    DecisionClient,
    DecisionUnavailable,
    Observation,
    digest,
    questions_for,
)

from evals.decisions import evaluate, load_cases, metrics  # noqa: E402


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.client = DecisionClient("synthetic-credential")
        self.state = {"query": "Which gateway is approved?", "passages": ["Use the managed gateway."]}
        self.questions = questions_for("input_context", self.state)

    def response(self):
        return {
            "model": JEV_RESOLVED_MODEL,
            "answers": {k: {"type": "noul", "noul": 0.1} for k in self.questions},
            "usage": {"cost": 0.0001},
        }

    def test_exact_keys_finite_probabilities_and_model_are_required(self):
        mutations = (
            lambda r: r["answers"].pop("input_override"),
            lambda r: r["answers"].update(extra={"type": "noul", "noul": 0.1}),
            lambda r: r["answers"]["input_override"].update(noul=float("nan")),
            lambda r: r["answers"]["input_override"].update(noul=True),
            lambda r: r["answers"]["input_override"].update(noul=1.1),
            lambda r: r["answers"]["input_override"].update(type="choice"),
            lambda r: r.update(model="typesafe/jev-next"),
            lambda r: r.update(usage={"cost": -1}),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                raw = self.response()
                mutation(raw)
                with self.assertRaises(DecisionUnavailable):
                    self.client.parse(raw, self.questions, 100)

    def test_provider_response_text_is_not_retained_in_observation(self):
        raw = self.response()
        raw["debug"] = "private text and credentials"
        result = self.client.parse(raw, self.questions, 20)
        self.assertNotIn("private", str(result.event("input_context")))

    def test_relevance_is_diagnostic_and_never_would_block(self):
        result = Observation(JEV_RESOLVED_MODEL, {"passage_0_relevant": 1.0}, 20, None)
        self.assertFalse(result.event("input_context")["would_block"])
        result = Observation(JEV_RESOLVED_MODEL, {"passage_0_attack": 0.8}, 20, None)
        self.assertTrue(result.event("input_context")["would_block"])

    def test_oversized_state_is_unavailable_before_network(self):
        self.client.opener = MagicMock()
        for state in (
            {**self.state, "passages": ["x"] * 7},
            {**self.state, "query": "я" * 48_000},
            {**self.state, "images": ["private image"]},
        ):
            with self.assertRaises(DecisionUnavailable):
                self.client.evaluate("input_context", state)
        self.client.opener.open.assert_not_called()

    def test_ungrounded_answer_does_not_get_a_support_score(self):
        questions = questions_for("output", {"query": "Hello", "passages": [], "answer": "Hi"})
        self.assertNotIn("output_unsupported", questions)

    def test_cloudflare_wrapper_and_account_validation(self):
        client = DecisionClient("synthetic", provider="cloudflare", model="clef-flash", account="a" * 32)
        raw = self.response()
        raw["model"] = "clef-flash"
        result = client.parse({"success": True, "result": raw}, self.questions, 20)
        self.assertEqual(result.model, "clef-flash")
        with self.assertRaises(DecisionUnavailable):
            client.parse({"success": False, "errors": ["private provider text"]}, self.questions, 20)
        with self.assertRaises(ValueError):
            DecisionClient("synthetic", provider="cloudflare", model="clef", account="../evil")
        with self.assertRaises(ValueError):
            DecisionClient("synthetic", model="~typesafe/jev-latest")

    def test_digest_is_order_stable_and_text_sensitive(self):
        self.assertEqual(digest({"b": 2, "a": 1}), digest({"a": 1, "b": 2}))
        self.assertNotEqual(digest(self.state), digest({**self.state, "query": "different"}))

    def test_unavailable_results_are_not_counted_as_safe(self):
        result = metrics(
            [
                {"label": True, "score": 0.9},
                {"label": True, "score": 0.1},
                {"label": False, "score": 0.9},
                {"label": False, "score": 0.1},
                {"label": True, "score": None},
            ]
        )
        self.assertEqual([result[k] for k in ("tp", "fn", "fp", "tn", "unavailable")], [1, 1, 1, 1, 1])
        self.assertEqual(result["accuracy_on_available"], 0.5)

    def test_benchmark_computes_pattern_baseline_and_keeps_raw_text_out(self):
        data = load_cases(Path(__file__).resolve().parents[1] / "evals/decision-cases.json")
        client = MagicMock(provider="openrouter", model="typesafe/jev-1.13")
        client.evaluate.side_effect = lambda stage, state: Observation(
            JEV_RESOLVED_MODEL, {k: 0.1 for k in questions_for(stage, state)}, 10, 0.0001
        )
        report = evaluate(client, data, {"corpus_version": "1.0.0", "manifest_sha256": "a" * 64})
        self.assertEqual(report["case_count"], 32)
        self.assertEqual(report["unavailable_calls"], 0)
        self.assertNotIn("state", report["calls"][0])
        self.assertGreater(report["metrics"]["risk/holdout/all"]["fn"], 0)


if __name__ == "__main__":
    unittest.main()
