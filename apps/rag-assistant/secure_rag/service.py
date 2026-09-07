from __future__ import annotations

from dataclasses import dataclass

from .gateway import ModelGateway
from .retrieval import Retriever

REFUSAL = "I do not have enough grounded context to answer this question."


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    confidence: float
    refused: bool
    citations: tuple[dict[str, str], ...]


class RAGService:
    def __init__(
        self,
        retriever: Retriever,
        gateway: ModelGateway,
        *,
        min_confidence: float,
        top_k: int,
    ) -> None:
        self._retriever = retriever
        self._gateway = gateway
        self._min_confidence = min_confidence
        self._top_k = top_k

    def ask(self, question: str, *, filters: dict[str, str] | None = None) -> Answer:
        results = self._retriever.search(question, filters=filters, top_k=self._top_k)
        confidence = self._retriever.confidence(results)
        citations_list: list[dict[str, str]] = []
        seen_sources: set[str] = set()
        for item in results:
            if item.chunk.document_id in seen_sources:
                continue
            seen_sources.add(item.chunk.document_id)
            citations_list.append(
                {
                    "source_id": item.chunk.document_id,
                    "title": item.chunk.title,
                    "path": item.chunk.source_path,
                }
            )
        citations = tuple(citations_list)
        if confidence < self._min_confidence:
            # Weak or empty retrieval is not evidence. Do not disclose document
            # identifiers/titles for a refused answer, since that would expose
            # the corpus inventory even when the question is out of scope.
            return Answer(text=REFUSAL, confidence=confidence, refused=True, citations=())
        return Answer(
            text=self._gateway.answer(question, results),
            confidence=confidence,
            refused=False,
            citations=citations,
        )
