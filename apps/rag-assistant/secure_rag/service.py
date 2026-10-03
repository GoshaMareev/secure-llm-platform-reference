from __future__ import annotations

from dataclasses import dataclass

from .authorization import PUBLIC_SCOPE, RetrievalScope
from .gateway import DemoGateway, ExtractiveAnswer, ModelGateway
from .guardrails import REDACTION_PLACEHOLDER, SCOPE_ACCESS_DENIED, Guardrails
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

    def ask(
        self,
        question: str,
        *,
        filters: dict[str, str] | None = None,
        scope: RetrievalScope = PUBLIC_SCOPE,
    ) -> Answer:
        verdicts: list[str] = []
        guard = self._guardrails
        audience = (filters or {}).get("audience")
        if audience is not None and audience.casefold() not in scope.audiences:
            return Answer(POLICY_REFUSAL, 0.0, True, (), (SCOPE_ACCESS_DENIED,), blocked=True)

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
        results = self._retriever.search(search_query, filters=filters, top_k=self._top_k, scope=scope)
        if guard is not None:
            screened = guard.screen_context(results)
            verdicts.extend(screened.verdicts)
            results = screened.kept

        confidence = self._retriever.confidence(results)
        if not isinstance(self._gateway, DemoGateway) and confidence < self._min_confidence:
            # Weak or empty retrieval is not evidence. Do not disclose document
            # identifiers/titles for a refused answer, since that would expose
            # the corpus inventory even when the question is out of scope.
            return Answer(REFUSAL, confidence, True, (), tuple(verdicts))

        if guard is not None:
            redacted = guard.redact_context(results)
            verdicts.extend(redacted.verdicts)
            if redacted.blocked:
                return Answer(POLICY_REFUSAL, confidence, True, (), tuple(verdicts), blocked=True)
            results = redacted.kept
        text = self._gateway.answer(question, results)
        used_sources = getattr(text, "source_ids", None)
        if isinstance(text, ExtractiveAnswer) and not used_sources:
            return Answer(REFUSAL, confidence, True, (), tuple(verdicts))
        if guard is not None:
            output = guard.check_output(text)
            verdicts.extend(output.verdicts)
            if output.blocked:
                return Answer(POLICY_REFUSAL, confidence, True, (), tuple(verdicts), blocked=True)
            text = output.text

        return Answer(
            str(text),
            confidence,
            False,
            _citations([r for r in results if used_sources is None or r.chunk.document_id in used_sources]),
            tuple(verdicts),
        )
