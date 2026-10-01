"""Personal-data redaction backed by Microsoft Presidio (English).

Presidio combines spaCy named-entity recognition (names) with validated
recognizers (Luhn for cards, IBAN checksum, phone-number parsing, SSN rules),
which a regex alone cannot do. Install ``requirements-presidio.txt`` and the
spaCy model before selecting ``PII_BACKEND=presidio``.
"""

from __future__ import annotations

import os

# Entity types this deployment treats as personal data, mapped to the kind used
# in placeholders and verdicts. DATE_TIME, LOCATION and NRP are deliberately
# excluded: policy text is full of dates and place-like nouns, and redacting
# them would destroy answers without protecting a person.
ENTITY_KINDS = {
    "PERSON": "person",
    "EMAIL_ADDRESS": "email",
    "PHONE_NUMBER": "phone",
    "CREDIT_CARD": "card",
    "IBAN_CODE": "iban",
    "US_SSN": "ssn",
    "IP_ADDRESS": "ip",
}
DEFAULT_MODEL = "en_core_web_sm"
DEFAULT_SCORE_THRESHOLD = 0.4


class PresidioPiiRedactor:
    def __init__(
        self,
        *,
        model: str | None = None,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine
            from presidio_anonymizer.entities import OperatorConfig
        except ImportError as error:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "PII_BACKEND=presidio requires requirements-presidio.txt and a spaCy English model"
            ) from error

        model_name = model or os.getenv("PRESIDIO_SPACY_MODEL", DEFAULT_MODEL)
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model_name}],
            }
        ).create_engine()
        # Built once: loading the spaCy pipeline is the expensive part.
        self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
        self._anonymizer = AnonymizerEngine()
        self._threshold = score_threshold
        self._operators = {
            entity: OperatorConfig("replace", {"new_value": f"[REDACTED_{kind.upper()}]"})
            for entity, kind in ENTITY_KINDS.items()
        }

    def redact(self, text: str) -> tuple[str, tuple[str, ...]]:
        findings = self._analyzer.analyze(
            text=text,
            language="en",
            entities=list(ENTITY_KINDS),
            score_threshold=self._threshold,
        )
        if not findings:
            return text, ()
        result = self._anonymizer.anonymize(
            text=text, analyzer_results=findings, operators=self._operators
        )
        kinds = tuple(dict.fromkeys(ENTITY_KINDS[item.entity_type] for item in result.items))
        return result.text, kinds
