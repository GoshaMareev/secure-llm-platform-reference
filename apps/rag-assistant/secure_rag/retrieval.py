from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ingestion.models import IndexedChunk
from ingestion.store import read_index
from ingestion.vectorizer import cosine_similarity, expand_tokens, tokenize, vectorize

from .authorization import PUBLIC_SCOPE, RetrievalScope


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk: IndexedChunk
    score: float
    lexical_score: float
    vector_score: float


def load_glossary(path: Path | None) -> dict[str, list[str]]:
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return {str(key).casefold(): [str(item).casefold() for item in items] for key, items in value.items()}


class Retriever:
    def __init__(self, index_path: Path, *, glossary: dict[str, list[str]] | None = None) -> None:
        payload, self._chunks = read_index(index_path)
        self.corpus = payload["corpus"]
        self.pipeline_sha256 = payload["pipeline_sha256"]
        self._glossary = glossary or {}

    @staticmethod
    def _matches_filters(chunk: IndexedChunk, filters: dict[str, str]) -> bool:
        return all(
            chunk.metadata.get(key, "").casefold() == value.casefold() for key, value in filters.items()
        )

    @staticmethod
    def _coverage(results: list[SearchResult], query_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        covered: set[str] = set()
        for result in results:
            covered.update(query_tokens.intersection(result.chunk.tokens))
        return len(covered) / len(query_tokens)

    def search(
        self,
        question: str,
        *,
        filters: dict[str, str] | None = None,
        top_k: int = 3,
        scope: RetrievalScope = PUBLIC_SCOPE,
    ) -> list[SearchResult]:
        base_tokens = tokenize(question)
        expanded_tokens = expand_tokens(base_tokens, self._glossary)
        query_set = set(expanded_tokens)
        query_vector = vectorize(expanded_tokens)
        requested_filters = filters or {}

        candidates: list[SearchResult] = []
        for chunk in self._chunks:
            if not scope.allows(chunk.metadata):
                continue
            if not self._matches_filters(chunk, requested_filters):
                continue
            chunk_set = set(chunk.tokens)
            lexical = len(query_set.intersection(chunk_set)) / max(1, len(query_set))
            vector = cosine_similarity(query_vector, chunk.vector)
            score = 0.58 * vector + 0.42 * lexical
            candidates.append(
                SearchResult(chunk=chunk, score=score, lexical_score=lexical, vector_score=vector)
            )

        baseline = sorted(candidates, key=lambda item: (-item.score, item.chunk.id))[:top_k]
        reranked = sorted(
            candidates,
            key=lambda item: (
                -(item.score + 0.10 * float(question.casefold() in item.chunk.text.casefold())),
                -item.lexical_score,
                item.chunk.id,
            ),
        )[:top_k]

        baseline_coverage = self._coverage(baseline, set(base_tokens))
        reranked_coverage = self._coverage(reranked, set(base_tokens))
        return baseline if reranked_coverage + 0.05 < baseline_coverage else reranked

    @staticmethod
    def confidence(results: list[SearchResult]) -> float:
        if not results:
            return 0.0
        strongest = results[0]
        if strongest.lexical_score == 0:
            return 0.0
        grounded_score = 0.68 * strongest.lexical_score + 0.32 * strongest.vector_score
        margin = strongest.score - results[1].score if len(results) > 1 else strongest.score
        return max(0.0, min(1.0, 0.92 * grounded_score + 0.08 * max(0.0, margin)))
