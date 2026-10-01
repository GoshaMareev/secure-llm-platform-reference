from __future__ import annotations

from dataclasses import dataclass

from .gateway import ModelGateway
from .guardrails import REDACTION_PLACEHOLDER, Guardrails
from .retrieval import Retriever, SearchResult

REFUSAL = "I do not have enough grounded context to answer this question."
POLICY_REFUSAL = "This request was declined by the assistant's usage policy."


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    confidence: float
    refused: bool
    citations: tuple[dict[str, str], ...]
    policy_verdicts: tuple[str, ...] = ()
    blocked: bool = False


def _citations(results: list[SearchResult]) -> tuple[dict[str, str], ...]:
    citations: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for item in results:
        if item.chunk.document_id in seen_sources:
            continue
        seen_sources.add(item.chunk.document_id)
        citations.append(
            {
                "source_id": item.chunk.document_id,
                "title": item.chunk.title,
                "path": item.chunk.source_path,
            }
        )
    return tuple(citations)


class RAGService:
    def __init__(
        self,
        retriever: Retriever,
        gateway: ModelGateway,
        *,
        min_confidence: float,
        top_k: int,
        guardrails: Guardrails | None = None,
    ) -> None:
        self._retriever = retriever
        self._gateway = gateway
        self._min_confidence = min_confidence
        self._top_k = top_k
        self._guardrails = guardrails

    def ask(self, question: str, *, filters: dict[str, str] | None = None) -> Answer:
        verdicts: list[str] = []
        guard = self._guardrails

        if guard is not None:
            decision = guard.check_input(question)
            verdicts.extend(decision.verdicts)
            if decision.blocked:
                # Nothing is retrieved for a blocked request, so the refusal
                # cannot leak corpus content or inventory.
                return Answer(POLICY_REFUSAL, 0.0, True, (), tuple(verdicts), blocked=True)
            question = decision.text

        # Redaction placeholders carry no meaning for retrieval; leaving them in
        # the query dilutes lexical coverage and lowers confidence.
        search_query = REDACTION_PLACEHOLDER.sub(" ", question)
        results = self._retriever.search(search_query, filters=filters, top_k=self._top_k)
        if guard is not None:
            screened = guard.screen_context(results)
            verdicts.extend(screened.verdicts)
            results = screened.kept

        confidence = self._retriever.confidence(results)
        if confidence < self._min_confidence:
            # Weak or empty retrieval is not evidence. Do not disclose document
            # identifiers/titles for a refused answer, since that would expose
            # the corpus inventory even when the question is out of scope.
            return Answer(REFUSAL, confidence, True, (), tuple(verdicts))

        text = self._gateway.answer(question, results)
        if guard is not None:
            output = guard.check_output(text)
            verdicts.extend(output.verdicts)
            if output.blocked:
                return Answer(POLICY_REFUSAL, confidence, True, (), tuple(verdicts), blocked=True)
            text = output.text

        return Answer(text, confidence, False, _citations(results), tuple(verdicts))
