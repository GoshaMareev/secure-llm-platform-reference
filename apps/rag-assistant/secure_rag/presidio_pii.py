"""Personal-data redaction through Presidio Analyzer and Anonymizer services (English).

Presidio runs as two containers shared by every consumer on the platform: this
service calls them over HTTP, and the LiteLLM gateway calls the same pair for
its own pre- and post-call guardrails. The application image therefore carries
no spaCy model, and detection rules change in one place.

Presidio combines spaCy named-entity recognition (names) with validated
recognizers (Luhn for cards, IBAN checksum, phone-number parsing, SSN rules),
which a regex alone cannot do.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .guardrails import PiiServiceError

# Entity types this deployment treats as personal data, mapped to the kind used
# in placeholders and verdicts. DATE_TIME, LOCATION and NRP are deliberately
# excluded: policy text is full of dates and place-like nouns, and redacting
# them would destroy answers without protecting a person. Keep this list in
# sync with gateway/litellm-config.yaml.
ENTITY_KINDS = {
    "PERSON": "person",
    "EMAIL_ADDRESS": "email",
    "PHONE_NUMBER": "phone",
    "CREDIT_CARD": "card",
    "IBAN_CODE": "iban",
    "US_SSN": "ssn",
    "IP_ADDRESS": "ip",
}
DEFAULT_SCORE_THRESHOLD = 0.4
MAX_RESPONSE_BYTES = 1_000_000


def _validated_base(url: str, name: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{name} must be an HTTP(S) URL without embedded credentials")
    return url.rstrip("/")


class PresidioHttpRedactor:
    def __init__(
        self,
        *,
        analyzer_url: str | None = None,
        anonymizer_url: str | None = None,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._analyzer = _validated_base(
            analyzer_url or os.getenv("PRESIDIO_ANALYZER_URL", "http://127.0.0.1:5002"),
            "PRESIDIO_ANALYZER_URL",
        )
        self._anonymizer = _validated_base(
            anonymizer_url or os.getenv("PRESIDIO_ANONYMIZER_URL", "http://127.0.0.1:5001"),
            "PRESIDIO_ANONYMIZER_URL",
        )
        self._threshold = score_threshold
        self._timeout = timeout_seconds
        self._operators = {
            entity: {"type": "replace", "new_value": f"[REDACTED_{kind.upper()}]"}
            for entity, kind in ENTITY_KINDS.items()
        }

    def _post(self, url: str, payload: dict[str, Any]) -> Any:
        request = Request(  # noqa: S310 - operator-configured service URL, scheme validated
            url,
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (URLError, TimeoutError, OSError) as error:
            raise PiiServiceError(f"Presidio request failed: {url}") from error
        if len(body) > MAX_RESPONSE_BYTES:
            raise PiiServiceError("Presidio response exceeds the size limit")
        try:
            return json.loads(body)
        except ValueError as error:
            raise PiiServiceError("Presidio returned invalid JSON") from error

    def redact(self, text: str) -> tuple[str, tuple[str, ...]]:
        findings = self._post(
            f"{self._analyzer}/analyze",
            {
                "text": text,
                "language": "en",
                "entities": list(ENTITY_KINDS),
                "score_threshold": self._threshold,
            },
        )
        if not isinstance(findings, list):
            raise PiiServiceError("Presidio analyzer returned an unexpected payload")
        try:
            findings = [item for item in findings if item.get("entity_type") in ENTITY_KINDS]
            analyzer_results = [
                {
                    "start": int(item["start"]),
                    "end": int(item["end"]),
                    "score": float(item["score"]),
                    "entity_type": item["entity_type"],
                }
                for item in findings
            ]
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise PiiServiceError("Presidio analyzer returned malformed findings") from error
        if not findings:
            return text, ()
        result = self._post(
            f"{self._anonymizer}/anonymize",
            {
                "text": text,
                "analyzer_results": analyzer_results,
                "anonymizers": self._operators,
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise PiiServiceError("Presidio anonymizer returned an unexpected payload")
        items = result.get("items") or findings
        kinds = tuple(
            dict.fromkeys(
                ENTITY_KINDS[item["entity_type"]]
                for item in items
                if isinstance(item, dict) and item.get("entity_type") in ENTITY_KINDS
            )
        )
        return result["text"], kinds
