from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable

TOKEN_PATTERN = re.compile(r"[^\W_][\w-]{1,}", re.IGNORECASE)
VECTOR_DIMENSIONS = 96
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "does",
    "for",
    "from",
    "is",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "who",
    "with",
    "fictional",
    "organization",
    "how",
    "when",
    "which",
    "whose",
    "whom",
    "must",
    "may",
    "need",
    "needed",
    "have",
    "has",
    "be",
    "been",
    "it",
    "its",
    "that",
    "those",
    "do",
    "did",
    "many",
    "people",
    "person",
    "required",
    "require",
    "requirements",
    "кто",
    "что",
    "как",
    "какие",
    "какой",
    "когда",
    "где",
    "через",
    "сколько",
    "должен",
    "должны",
    "нужно",
    "нужны",
    "можно",
    "ли",
    "это",
    "этот",
    "для",
    "при",
    "его",
    "её",
    "какая",
    "каких",
    "чьё",
    "чье",
    "а",
    "и",
    "в",
    "на",
    "с",
    "ordinary",
    "indefinitely",
    "valid",
    "last",
    "after",
    "before",
    "twenty-four",
    "hours",
    "alone",
    "vendor",
    "two",
    "both",
}


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for match in TOKEN_PATTERN.finditer(text)
        if (token := match.group(0).casefold()) not in STOPWORDS
    )


def expand_tokens(tokens: Iterable[str], glossary: dict[str, list[str]]) -> tuple[str, ...]:
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(term.casefold() for term in glossary.get(token, []))
    return tuple(expanded)


def vectorize(tokens: Iterable[str], dimensions: int = VECTOR_DIMENSIONS) -> tuple[float, ...]:
    values = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        position = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        values[position] += sign

    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude == 0:
        return tuple(values)
    return tuple(value / magnitude for value in values)


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    score = sum(a * b for a, b in zip(left, right, strict=True))
    return max(0.0, min(1.0, score))
