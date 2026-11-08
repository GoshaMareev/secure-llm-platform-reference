"""Local media inspection before model routing. Raw audio is never forwarded."""

from __future__ import annotations

import base64
import binascii
import http.client
import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .guardrails import CONTEXT_ONLY_RULES, EXFILTRATION_RULES, INJECTION_RULES, PiiServiceError, _matches

MEDIA_POLICY_VERSION = "local-media-4"
ASR_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
MAX_MEDIA_BYTES = 4_000_000
MAX_MEDIA_PARTS = 4
MAX_EXTRACTED_CHARACTERS = 12_000

# High precision credentials, including secrets not covered by PII recognizers.
_CREDENTIAL = re.compile(
    r"(?i)\b(?:api[ _-]?(?:key|ключ)|password|пароль|секретный[ _-]?ключ|secret[ _-]?key|"
    r"access[ _-]?token)\s*[:=]\s*\S+"
    r"|\bBearer\s+[A-Za-z0-9._-]{12,}"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
_SPOKEN_EMAIL = re.compile(
    r"(?i)\b([a-z0-9][a-z0-9._-]*)(?:\s+(?:at|собака)\s+|\s*@\s*)"
    r"([a-z0-9-]+)(?:\s+(?:dot|точка)\s+|\s*\.\s*)([a-z]{2,})\b"
)
# ASR can confidently mishear a spelled address or number. Explicit sensitive
# labels with no matching redaction are denied, rather than trusting confidence.
_AUDIO_SENSITIVE_CUES = (
    (re.compile(r"(?i)\b(?:my\s+name\s+is|меня\s+зовут)\b"), "person"),
    (re.compile(r"(?i)\bbearer\b|\bbare[ ,]+a\b[^.]{0,60}\btoken\b"), "credential"),
    (re.compile(r"(?i)\b(?:e[- ]?mail(?:\s+address)?|электронная\s+почта|почта)\b"), "email"),
    (re.compile(r"(?i)\b(?:phone|telephone|mobile)\s+number|телефон\w*\b"), "phone"),
    (re.compile(r"(?i)\b(?:credit|payment)\s+card|(?:номер\s+)?карт[аыу]\b"), "card"),
    (
        re.compile(r"(?i)\b(?:password|парол\w*|api[ _-]?(?:key|ключ)|secret[ _-]?key|access[ _-]?token)\b"),
        "credential",
    ),
)

# OCR/STT is data, never authority to transfer material to external recipients.
# Deliberately independent of a correctly recognized word such as API token.
_MEDIA_EXTERNAL_ACTION = re.compile(
    r"(?i)^\s*(?:отправь|перешли|передай|загрузи|send|forward|upload)\b"
    r"[^\n.!?]{0,300}(?:поставщик|провайдер|внешн|vendor|provider|external|https?://)"
)


DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ноль": "0",
    "нуль": "0",
    "один": "1",
    "одна": "1",
    "два": "2",
    "две": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
}
DIGIT_WORD = "(?:" + "|".join(DIGIT_WORDS) + ")"
SPOKEN_NUMBER = re.compile(r"(?i)\b" + DIGIT_WORD + r"(?:[ ,.-]+" + DIGIT_WORD + r"){6,18}\b")


def normalize_spoken(text: str) -> str:
    text = _SPOKEN_EMAIL.sub(r"\1@\2.\3", text)

    def number(match):
        return "".join(DIGIT_WORDS[w.casefold()] for w in re.findall(DIGIT_WORD, match.group(), re.I))

    return SPOKEN_NUMBER.sub(number, text)


class MediaRejected(Exception):
    """A stable public verdict; never raw media, transcripts, or provider errors."""


def decode_base64(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > (MAX_MEDIA_BYTES + 2) // 3 * 4:
        raise MediaRejected("media_size_limit")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise MediaRejected("invalid_media_encoding") from None
    if not raw or len(raw) > MAX_MEDIA_BYTES:
        raise MediaRejected("media_size_limit")
    return raw


@dataclass(frozen=True)
class MediaResult:
    part: dict
    kind: str
    verdict: str
    redacted_kinds: tuple[str, ...]
    untrusted_text: str = ""


class LocalMediaInspector:
    def __init__(self, pii):
        self.pii = pii
        # No caller-configurable host, URL fetching or provider credentials.
        self.endpoint = "http://media-inspector:8090/inspect"
        self.timeout = 45.0
        self.opener = urllib.request.build_opener(_NoRedirect())

    def _inspect(self, kind: str, data: str, format: str) -> dict:
        request = urllib.request.Request(  # noqa: S310 - fixed internal service endpoint
            self.endpoint,
            data=json.dumps({"kind": kind, "data": data, "format": format}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(6_000_001)
            if len(raw) > 6_000_000:
                raise MediaRejected("media_check_unavailable")
            result = json.loads(raw)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError):
            raise MediaRejected("media_check_unavailable") from None
        if not isinstance(result, dict) or result.get("schema_version") != 1 or result.get("kind") != kind:
            raise MediaRejected("media_check_unavailable")
        if result.get("status") != "ok":
            # Only locally defined reason codes may cross the audit boundary.
            reason = result.get("reason")
            if reason not in {
                "invalid_media",
                "media_dimensions_limit",
                "media_duration_limit",
                "media_low_confidence",
                "media_no_speech",
                "media_language_not_supported",
                "media_check_unavailable",
                "media_capacity_exhausted",
            }:
                reason = "media_check_unavailable"
            raise MediaRejected(reason)
        text, confidence = result.get("text"), result.get("confidence")
        if (
            not isinstance(text, str)
            or len(text) > MAX_EXTRACTED_CHARACTERS
            or isinstance(confidence, bool)
            or not isinstance(confidence, (float, int))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise MediaRejected("media_check_unavailable")
        if kind == "audio" and (
            result.get("revision") != ASR_REVISION or result.get("language") not in {"en", "ru"}
        ):
            raise MediaRejected("media_check_unavailable")
        if confidence < (0.65 if kind == "image" else 0.45):
            raise MediaRejected("media_low_confidence")
        return result

    def check(self, part: dict) -> MediaResult:
        type_ = part.get("type")
        if type_ == "image_url":
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else None
            if not isinstance(url, str) or not url.startswith("data:"):
                raise MediaRejected("remote_media_blocked")
            match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,(.+)", url, re.DOTALL)
            if not match:
                raise MediaRejected("unsupported_media_format")
            format_, data = match.groups()
            kind = "image"
        elif type_ == "input_audio":
            audio = part.get("input_audio")
            if not isinstance(audio, dict) or audio.get("format") not in {"wav", "mp3"}:
                raise MediaRejected("unsupported_media_format")
            data, format_, kind = audio.get("data"), audio["format"], "audio"
        else:
            # Unknown media representations, video and file URLs cannot bypass inspection.
            raise MediaRejected("unsupported_media_input")
        decode_base64(data)
        result = self._inspect(kind, data, format_)
        text = result["text"]
        if kind == "audio":
            text = normalize_spoken(text)
            # A literal mask supplied by OCR/STT is data, not proof that our
            # redactor removed a value. Only masks created below can resolve cues.
            text = re.sub(r"\[REDACTED_[A-Z_]+\]", "[UNTRUSTED_MASK_LITERAL]", text, flags=re.I)
        if _matches(
            text, (*INJECTION_RULES, *EXFILTRATION_RULES, *CONTEXT_ONLY_RULES)
        ) or _MEDIA_EXTERNAL_ACTION.search(text):
            raise MediaRejected("media_injection_blocked")
        credential_matches = list(_CREDENTIAL.finditer(text))
        if kind == "audio" and any(
            any(separator in match.group() for separator in (":", "=")) and text[match.end() :].strip()
            for match in credential_matches
        ):
            # A colon-labelled secret may span several words. Removing just
            # its first token would consume the cue and leave an unchecked tail.
            raise MediaRejected("audio_sensitive_text_unresolved")
        secret = bool(credential_matches)
        if secret:
            text = _CREDENTIAL.sub("[REDACTED_CREDENTIAL]", text)
        try:
            clean, kinds = self.pii.redact(text) if text else (text, ())
        except PiiServiceError:
            raise MediaRejected("pii_check_unavailable_blocked") from None
        kinds = tuple(dict.fromkeys((*kinds, *(("credential",) if secret else ()))))
        if kind == "audio":
            # Associate every remaining label with its own following mask.
            # A mask elsewhere cannot waive another unresolved value.
            for cue, entity in _AUDIO_SENSITIVE_CUES:
                matches = list(cue.finditer(clean))
                for i, match in enumerate(matches):
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(clean)
                    tail = re.split(r"[.!?\n]", clean[match.end() : min(end, match.end() + 120)])[0]
                    # Only grammatical separators may occur between the
                    # label and its mask. An unresolved value followed by a
                    # different masked value cannot satisfy this cue.
                    resolved = re.match(
                        r"(?i)^(?:\s|[:=,\-—\"'«»]|\b(?:is|это|number|номер|address|адрес|равен|равна)\b){0,40}"
                        + re.escape(f"[REDACTED_{entity.upper()}]"),
                        tail,
                    )
                    if not resolved:
                        raise MediaRejected("audio_sensitive_text_unresolved")
        if kind == "image":
            if kinds or clean != text:
                raise MediaRejected("image_sensitive_text_blocked")
            clean_data = result.get("clean_data")
            if not decode_base64(clean_data).startswith(b"\x89PNG\r\n\x1a\n"):
                raise MediaRejected("media_check_unavailable")
            # Re-encoded pixels, with EXIF/comments/embedded metadata removed.
            safe = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + clean_data}}
            return MediaResult(safe, kind, "image_text_checked", (), clean)
        if not clean.strip():
            raise MediaRejected("media_no_speech")
        return MediaResult(
            {"type": "text", "text": "[Locally transcribed audio]\n" + clean},
            kind,
            "audio_transcript_redacted" if kinds else "audio_transcript_checked",
            kinds,
            clean,
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
