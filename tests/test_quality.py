"""Meaningful metric denominators and regression gates, independent of retrieval."""

import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.quality import (  # noqa: E402
    Observation,
    diagnostic_path,
    fact_supported,
    gate,
    observe_native,
    score,
)


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "id": "multi",
            "category": "multi_fact",
            "expected_sources": ["a", "b"],
            "fact_groups": [["sixty minutes", "one hour"], ["commander"]],
            "expect_refusal": False,
            "forbidden_sources": ["private"],
            "forbidden_fragments": ["restricted secret"],
        }

    def test_partial_retrieval_and_fact_coverage_do_not_pass(self):
        row = score(
            self.case,
            Observation("Access expires after one hour", ["a", "noise"], ["noise", "a", "a"], False, True),
        )
        self.assertEqual(row["retrieval_recall"], 0.5)
        self.assertEqual(row["reciprocal_rank"], 0.5)
        self.assertEqual(row["fact_coverage"], 0.5)
        self.assertEqual(row["source_precision"], 0.5)
        self.assertFalse(row["passed"])

    def test_all_reference_facts_and_sources_needed(self):
        row = score(
            self.case,
            Observation(
                "The incident commander approves access; Access expires after sixty minutes",
                ["a", "b"],
                ["b", "a"],
                False,
                True,
            ),
        )
        self.assertTrue(row["passed"])
        self.assertEqual(row["fact_coverage"], 1)
        self.assertEqual(row["retrieval_recall"], 1)

    def test_unavailable_service_never_counts_as_correct_refusal(self):
        case = {**self.case, "expect_refusal": True, "expected_sources": [], "fact_groups": []}
        row = score(case, Observation("", [], [], True, False, error=True))
        self.assertFalse(row["refusal_correct"])
        self.assertFalse(row["passed"])
        self.assertIsNone(row["citation_valid"])
        self.assertIsNone(row["retrieval_recall"])

    def test_forbidden_retrieved_context_is_a_leak_even_without_citation(self):
        row = score(
            self.case,
            Observation(
                "The incident commander approves access; Access expires after one hour",
                ["a", "b"],
                ["a", "private"],
                False,
                True,
            ),
        )
        self.assertTrue(row["leak"])
        self.assertFalse(row["passed"])

    def test_baseline_cannot_waive_leak_and_each_case_is_gated(self):
        row = score(
            self.case,
            Observation(
                "The incident commander approves access; Access expires after one hour",
                ["a", "b"],
                ["a", "b"],
                False,
                True,
            ),
        )
        result = dict(backend="offline", manifest_sha256="corpus", suite_sha256="suite", cases=[row])
        baseline = copy.deepcopy(result)
        result["cases"][0]["fact_coverage"] = 0.5
        self.assertIn("multi: regressed fact_coverage", gate(result, baseline))
        result["cases"][0]["leak"] = True
        self.assertIn("multi: leak or runtime error", gate(result, result))
        result["suite_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "different"):
            gate(result, baseline)

    def test_negation_contradiction_and_keyword_lists_do_not_earn_credit(self):
        for answer in (
            "Access does not expire after sixty minutes. The incident commander does not approve it.",
            "Access expires after sixty minutes. Access does not expire after sixty minutes.",
            "Keywords: commander; sixty minutes",
            'The keyword "commander" appears in the index.',
        ):
            self.assertFalse(
                score(self.case, Observation(answer, ["a", "b"], ["a", "b"], False, True))["passed"]
            )
        self.assertTrue(fact_supported("Shared accounts are prohibited.", ["prohibited"]))
        self.assertFalse(fact_supported("Shared accounts are not prohibited.", ["prohibited"]))
        self.assertFalse(
            fact_supported("Shared accounts are prohibited. They are not prohibited.", ["prohibited"])
        )

    def test_rejecting_a_false_premise_does_not_negate_the_correction(self):
        self.assertTrue(fact_supported("No, access expires after sixty minutes.", ["sixty minutes"]))
        self.assertFalse(fact_supported("No, access never expires after sixty minutes.", ["sixty minutes"]))

    def test_reviewed_russian_measurement_equivalents_keep_polarity(self):
        self.assertTrue(fact_supported("Доступ истекает через шестьдесят минут.", ["60 минут"]))
        self.assertFalse(fact_supported("Доступ не истекает через шестьдесят минут.", ["60 минут"]))
        self.assertTrue(fact_supported("Требуется утвержденная роль для доступа.", ["утверждён"]))
        self.assertTrue(fact_supported("Сохраняются запросы и решения политики.", ["verdict"]))
        self.assertTrue(
            fact_supported(
                "Идентичности не могут быть повторно использованы между компонентами.", ["may not be reused"]
            )
        )
        self.assertFalse(fact_supported("Решения политики не сохраняются во время инцидента.", ["verdict"]))

    def test_raw_diagnostics_cannot_be_written_to_public_report(self):
        with self.assertRaisesRegex(ValueError, "under .local"):
            diagnostic_path(ROOT / "docs" / "unsafe-diagnostics.json")


class NativeObservationTests(unittest.TestCase):
    def response(self, payload, status=200):
        return SimpleNamespace(status_code=status, json=lambda: payload)

    def test_numeric_citations_resolve_to_original_source_ids(self):
        corpus = {"documents": [{"id": "a", "path": "documents/a.md"}]}
        response = self.response(
            {
                "choices": [{"message": {"content": "Reference fact [1]."}}],
                "sources": [{"document": ["Reference fact"], "metadata": [{"source": "a.md"}]}],
            }
        )
        observation = observe_native(response, corpus)
        self.assertEqual(observation.sources, ["a"])
        self.assertTrue(observation.citation_valid)
        self.assertFalse(observation.refused)
        response.json()["choices"][0]["message"]["content"] = "Reference fact [7]."
        self.assertFalse(observe_native(response, corpus).citation_valid)

    def test_native_transport_and_control_failure_are_not_safe_abstention(self):
        for status, verdict in (
            (502, None),
            (400, "external_rerank_required"),
            (400, "pii_check_unavailable_blocked"),
        ):
            observation = observe_native(self.response({"detail": {"verdict": verdict}}, status), {})
            self.assertTrue(observation.error)
        generic = observe_native(self.response({"detail": "Blocked by policy"}, 400), {})
        self.assertTrue(generic.error)
        safe = observe_native(self.response({"detail": {"verdict": "no_safe_evidence"}}, 400), {})
        self.assertFalse(safe.error)
        self.assertTrue(safe.refused)

    def test_prohibiting_provider_url_is_not_classified_as_refusal(self):
        observation = observe_native(
            self.response(
                {"choices": [{"message": {"content": "Applications must not accept provider URLs."}}]}
            ),
            {"documents": []},
        )
        self.assertFalse(observation.refused)

    def test_complete_cited_policy_explanation_is_not_a_refusal(self):
        corpus = {"documents": [{"id": "a", "path": "a.md"}]}
        response = self.response(
            {
                "choices": [
                    {"message": {"content": "When evidence is insufficient, the assistant must refuse [1]."}}
                ],
                "sources": [{"document": ["Reference fact"], "metadata": [{"source": "a.md"}]}],
            }
        )
        case = {"expected_sources": ["a"], "fact_groups": [["refuse"]]}
        self.assertFalse(observe_native(response, corpus, case).refused)
