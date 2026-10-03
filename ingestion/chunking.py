from __future__ import annotations


def chunk_text(text: str, *, max_words: int = 90, overlap_words: int = 18) -> list[str]:
    if max_words < 8:
        raise ValueError("max_words must be at least 8")
    if overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("overlap_words must be between 0 and max_words - 1")

    words = text.split()
    if not words:
        return []

    step = max_words - overlap_words
    chunks: list[str] = []
    for start in range(0, len(words), step):
        part = words[start : start + max_words]
        if part:
            chunks.append(" ".join(part))
        if start + max_words >= len(words):
            break
    return chunks
