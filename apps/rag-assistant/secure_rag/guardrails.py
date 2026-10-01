"""Deterministic policy checks around the retrieval and generation path.

The checks are intentionally transparent heuristics. They show where policy runs
(input, retrieved context, output), what each stage may do (block, redact,
quarantine), and how verdicts are recorded. A production deployment would put a
trained classifier behind the same ``Guardrails`` interface; see ADR 0004.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from .gateway import SYSTEM_PROMPT
from .retrieval import SearchResult

# Verdict codes are stable identifiers. They are safe for operational telemetry:
# they describe which control fired, never the text that triggered it.
INPUT_INJECTION = "input_injection_blocked"
INPUT_PII = "input_pii_redacted"
CONTEXT_INJECTION = "context_injection_quarantined"
OUTPUT_PII = "output_pii_redacted"
OUTPUT_PROMPT_LEAK = "output_prompt_leak_blocked"
OUTPUT_INJECTION_ECHO = "output_injection_echo_blocked"

ALL_VERDICTS = (
    INPUT_INJECTION,
    INPUT_PII,
    CONTEXT_INJECTION,
    OUTPUT_PII,
    OUTPUT_PROMPT_LEAK,
    OUTPUT_INJECTION_ECHO,
)

_INVISIBLE = re.compile("[­᠎​-‏‪-‮⁠-⁤﻿]")
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Fold common obfuscation (width variants, invisible characters, case, spacing)."""
    folded = unicodedata.normalize("NFKC", text)
    folded = _INVISIBLE.sub("", folded)
    return _WHITESPACE.sub(" ", folded).casefold().strip()


@dataclass(frozen=True, slots=True)
class _Rule:
    name: str
    pattern: re.Pattern[str]


def _rule(name: str, pattern: str) -> _Rule:
    return _Rule(name, re.compile(pattern, re.IGNORECASE))


# Instructions aimed at the model rather than questions about the corpus.
# Each rule needs both an action verb and an instruction-like target so that
# ordinary policy questions ("which instructions apply...", "can I act as
# incident commander?") are not blocked. Benign probes in evals/cases.jsonl
# measure the false-positive side of these rules.
INJECTION_RULES = (
    _rule(
        "override-instructions",
        r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?"
        r"\b(?:previous|prior|above|earlier|all|any|your|these|those)\b[^.\n]{0,20}?"
        r"\b(?:instructions?|rules|polic(?:y|ies)|guidelines|prompts?|directives|guardrails)\b",
    ),
    _rule(
        "reveal-system-prompt",
        r"\b(?:reveal|print|show|repeat|output|leak|display|dump)\b[^.\n]{0,30}?"
        r"\b(?:system|hidden|initial|secret|original)\s+(?:prompt|instructions?|message)",
    ),
    _rule(
        "role-override",
        r"\byou are now\b"
        r"|\b(?:developer|god|jailbreak|dan)\s+mode\b"
        r"|\b(?:pretend|act)\s+(?:to be|as|like)\s+(?:an?\s+)?"
        r"(?:unrestricted|unfiltered|uncensored|jailbroken|different)\b",
    ),
    _rule(
        "override-instructions-ru",
        r"\b(?:игнорируй|проигнорируй|игнорировать|забудь|отмени)\b[^.\n]{0,40}?"
        r"\b(?:инструкци\w*|правил\w*|указани\w*|ограничени\w*)",
    ),
    _rule(
        "reveal-system-prompt-ru",
        r"\b(?:покажи|выведи|раскрой|повтори)\b[^.\n]{0,30}?\bсистемн\w*\s+(?:промпт\w*|инструкци\w*)",
    ),
)

# Text that tells the *reader* to hand over secrets. Asked by a user it is a
# legitimate question ("should I send my token to X?"); found in a document or
# an answer it is an exfiltration attempt. Checked on context and output only.
EXFILTRATION_RULES = (
    _rule(
        "credential-exfiltration",
        r"\b(?:send|forward|post|email|upload|paste|share)\b[^.\n]{0,40}?"
        r"\b(?:credentials?|passwords?|tokens?|api keys?|secrets?)\b",
    ),
)

# Markers that only make sense inside a document if someone is trying to speak
# to the model. Checked on retrieved context, not on user questions.
CONTEXT_ONLY_RULES = (
    _rule(
        "fake-role-marker",
        r"(?:^|[\n.!?]\s*)(?:system|assistant|developer)\s*:"
        r"|<\s*/?\s*(?:system|instructions?)\s*>"
        r"|\[\s*(?:system|inst)\s*\]",
    ),
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
REDACTION_PLACEHOLDER = re.compile(r"\[REDACTED_[A-Z]+\]")
_PHONE_CANDIDATE = re.compile(r"(?<![\w+])\+?\d[\d ().-]{7,}\d(?!\w)")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for position, character in enumerate(reversed(digits)):
        value = int(character)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, tuple[str, ...]]:
    """Replace e-mail addresses, payment card numbers and phone numbers with typed placeholders."""
    kinds: list[str] = []

    def card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            kinds.append("card")
            return "[REDACTED_CARD]"
        return match.group(0)

    def phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 10 <= len(digits) <= 15:
            kinds.append("phone")
            return "[REDACTED_PHONE]"
        return match.group(0)

    def email(match: re.Match[str]) -> str:
        kinds.append("email")
        return "[REDACTED_EMAIL]"

    redacted = _EMAIL.sub(email, text)
    redacted = _CARD_CANDIDATE.sub(card, redacted)
    redacted = _PHONE_CANDIDATE.sub(phone, redacted)
    return redacted, tuple(dict.fromkeys(kinds))


def _matches(text: str, rules: Iterable[_Rule]) -> tuple[str, ...]:
    normalized = normalize(text)
    return tuple(rule.name for rule in rules if rule.pattern.search(normalized))


@dataclass(frozen=True, slots=True)
class InputDecision:
    text: str
    blocked: bool
    verdicts: tuple[str, ...]
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextDecision:
    kept: list[SearchResult]
    quarantined_chunk_ids: tuple[str, ...]
    verdicts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutputDecision:
    text: str
    blocked: bool
    verdicts: tuple[str, ...]


class Guardrails:
    """Three checkpoints: user input, retrieved context, and model output."""

    def __init__(self, *, system_prompt: str = SYSTEM_PROMPT) -> None:
        # A long, distinctive fragment of the operator prompt. Seeing it in an
        # answer means the model repeated its instructions.
        self._prompt_fingerprint = normalize(system_prompt)[:48]

    def check_input(self, question: str) -> InputDecision:
        rules = _matches(question, INJECTION_RULES)
        if rules:
            return InputDecision(text="", blocked=True, verdicts=(INPUT_INJECTION,), rules=rules)
        redacted, kinds = redact_pii(question)
        verdicts = (INPUT_PII,) if kinds else ()
        return InputDecision(text=redacted, blocked=False, verdicts=verdicts, rules=())

    def screen_context(self, results: list[SearchResult]) -> ContextDecision:
        kept: list[SearchResult] = []
        quarantined: list[str] = []
        for result in results:
            if _matches(result.chunk.text, (*INJECTION_RULES, *EXFILTRATION_RULES, *CONTEXT_ONLY_RULES)):
                quarantined.append(result.chunk.id)
            else:
                kept.append(result)
        verdicts = (CONTEXT_INJECTION,) if quarantined else ()
        return ContextDecision(kept=kept, quarantined_chunk_ids=tuple(quarantined), verdicts=verdicts)

    def check_output(self, answer: str) -> OutputDecision:
        normalized = normalize(answer)
        if self._prompt_fingerprint and self._prompt_fingerprint in normalized:
            return OutputDecision(text="", blocked=True, verdicts=(OUTPUT_PROMPT_LEAK,))
        if _matches(answer, (*INJECTION_RULES, *EXFILTRATION_RULES)):
            return OutputDecision(text="", blocked=True, verdicts=(OUTPUT_INJECTION_ECHO,))
        redacted, kinds = redact_pii(answer)
        return OutputDecision(text=redacted, blocked=False, verdicts=(OUTPUT_PII,) if kinds else ())
