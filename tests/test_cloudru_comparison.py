"""Partial masks, benign changes and outages cannot count as protection."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/rag-assistant")]
from secure_rag.cloudru_pii import ScanSummary, ScanUnavailable  # noqa: E402
from secure_rag.guardrails import PiiServiceError  # noqa: E402

from evals.cloudru_cases import CASES, Case, sensitive  # noqa: E402
from evals.cloudru_comparison import aggregate, evaluate, masked_positions, score  # noqa: E402


class ComparisonTests(unittest.TestCase):
    def test_fixture_spans_are_fixed_unique_and_valid(self):
        self.assertEqual(len(CASES), 64)
        self.assertEqual(len({case.id for case in CASES}), 64)
        self.assertEqual(sum(len(case.spans) for case in CASES), 50)
        for case in CASES:
            for start, end in case.spans:
                self.assertTrue(0 <= start < end <= len(case.text))

    def test_partial_name_is_a_miss_and_extra_masking_remains_visible(self):
        case = sensitive("name", "names", "Contact: ", "Анна Смирнова")
        self.assertEqual(score(case, set(range(9, 13)))["protected_values"], 0)
        overmask = score(case, set(range(len(case.text))))
        self.assertEqual(overmask["protected_values"], 1)
        self.assertEqual(overmask["extra_masked_characters"], 9)

    def test_placeholder_letters_are_not_counted_as_surviving_personal_data(self):
        case = sensitive("name", "names", "Contact: ", "ANNA")
        result = score(case, masked_positions(case.text, "Contact: [REDACTED_PERSON]"))
        self.assertEqual(result["protected_values"], 1)
        self.assertEqual(result["extra_masked_characters"], 0)

    def test_benign_partial_replacement_is_a_false_positive(self):
        case = Case("benign", "benign", "Version 1.2.3", ())
        self.assertFalse(score(case, {8, 9})["benign_unchanged"])

    def test_unavailable_detector_is_a_reported_miss(self):
        row = {"id": "probe", "sensitive": True, "cloudru": {"status": "unavailable", "latency_ms": 2}}
        result = aggregate([row], "cloudru")
        self.assertEqual(result["unavailable"], 1)
        self.assertEqual(result["protected_values"], 0)
        self.assertEqual(result["miss_ids"], ["probe"])

    def test_report_has_no_values_and_residual_does_not_imply_redaction(self):
        class Scanner:
            def spans(self, text):
                return set()

            def scan(self, texts):
                return ScanSummary(1, 1, 1, (3,))

        class Redactor:
            def redact(self, text):
                return text, ()

        case = sensitive("secret", "secrets", "Secret: ", "SyntheticSensitiveValue")
        with patch("evals.cloudru_comparison.CASES", [case]):
            report = evaluate(Scanner(), Redactor())
        self.assertEqual(report["residual"]["detected_cases"], 1)
        self.assertEqual(report["summary"]["cloudru"]["protected_values"], 0)
        self.assertNotIn("SyntheticSensitiveValue", repr(report))

    def test_missing_presidio_skips_residual_scan(self):
        class Scanner:
            def spans(self, text):
                raise ScanUnavailable("service_unavailable")

            def scan(self, texts):
                raise AssertionError("Unchecked Presidio text reached residual scan")

        class Redactor:
            def redact(self, text):
                raise PiiServiceError("unavailable")

        with patch("evals.cloudru_comparison.CASES", [CASES[0]]):
            report = evaluate(Scanner(), Redactor())
        self.assertEqual(report["residual"]["checked_cases"], 0)


if __name__ == "__main__":
    unittest.main()
