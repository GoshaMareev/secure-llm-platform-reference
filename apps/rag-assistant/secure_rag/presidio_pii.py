"""Personal-data redaction through Presidio Analyzer and Anonymizer services (English and Russian).

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
import math
import os
import re
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .guardrails import PiiServiceError, redact_pii
from .telemetry import MODEL_ALIAS, STAGE_SECONDS

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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
        self._opener = build_opener(NoRedirect())
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
        start = time.monotonic()
        verdict = "unavailable"
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise PiiServiceError("Presidio response exceeds the size limit")
            result = json.loads(body)
            verdict = "completed"
            return result
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise PiiServiceError("Presidio request unavailable") from error
        finally:
            STAGE_SECONDS.labels(stage="pii", model_alias=MODEL_ALIAS.get(), verdict=verdict).observe(
                time.monotonic() - start
            )

    def redact(self, text: str) -> tuple[str, tuple[str, ...]]:
        findings = []
        # English validated recognizers run for every input; Russian NER is
        # additionally mandatory for Cyrillic and mixed-language inputs.
        languages = ("en", "ru") if re.search(r"[А-Яа-яЁё]", text) else ("en",)
        try:
            for language in languages:
                detected = self._post(
                    f"{self._analyzer}/analyze",
                    {
                        "text": text,
                        "language": language,
                        "entities": list(ENTITY_KINDS),
                        "score_threshold": self._threshold,
                    },
                )
                if not isinstance(detected, list):
                    raise PiiServiceError("Presidio analyzer returned an unexpected payload")
                for item in detected:
                    if item.get("entity_type") not in ENTITY_KINDS:
                        continue
                    start, end, score = int(item["start"]), int(item["end"]), float(item["score"])
                    if not (0 <= start < end <= len(text)) or not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError("Invalid span")
                    # English NER is not evidence for an entirely Cyrillic name.
                    # Russian NER handles that script; retain mixed/Latin EN spans.
                    if (
                        language == "en"
                        and item["entity_type"] == "PERSON"
                        and re.search(r"[А-Яа-яЁё]", text[start:end])
                        and not re.search(r"[A-Za-z]", text[start:end])
                    ):
                        continue
                    findings.append(
                        {"start": start, "end": end, "score": score, "entity_type": item["entity_type"]}
                    )
            # Union overlapping spans before masking; never allow one language
            # to narrow the sensitive span found by the other language.
            analyzer_results = []
            for finding in sorted(findings, key=lambda x: (x["start"], x["end"])):
                if analyzer_results and finding["start"] < analyzer_results[-1]["end"]:
                    previous = analyzer_results[-1]
                    previous["end"] = max(previous["end"], finding["end"])
                    if finding["score"] > previous["score"]:
                        previous["entity_type"], previous["score"] = finding["entity_type"], finding["score"]
                else:
                    analyzer_results.append(dict(finding))
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise PiiServiceError("Presidio analyzer returned malformed findings") from error
        if not findings:
            return redact_pii(text)
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
        # Apply fallback after NER/checksums so phone patterns cannot split an IBAN.
        # The remote verdict remains mandatory even when fallback finds an email.
        redacted, fallback_kinds = redact_pii(result["text"])
        return redacted, tuple(dict.fromkeys((*kinds, *fallback_kinds)))
