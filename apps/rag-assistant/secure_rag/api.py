from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator

from .audit import AuditWriter, OperationalEvent, OperationalLogger
from .gateway import DemoGateway, OpenAICompatibleGateway
from .guardrails import Guardrails
from .retrieval import Retriever, load_glossary
from .service import RAGService
from .settings import Settings

REQUESTS = Counter("rag_requests_total", "RAG API requests", ["status", "refused"])
LATENCY = Histogram("rag_request_duration_seconds", "RAG request latency")
POLICY_VERDICTS = Counter("rag_policy_verdicts_total", "Guardrail verdicts by control", ["verdict"])


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4_000)
    filters: dict[str, str] = Field(default_factory=dict)
    actor_id: str = Field(default="anonymous", min_length=1, max_length=128)

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, filters: dict[str, str]) -> dict[str, str]:
        if len(filters) > 8:
            raise ValueError("at most 8 filters are allowed")
        for key, value in filters.items():
            if not 1 <= len(key) <= 64 or not 1 <= len(value) <= 128:
                raise ValueError("filter keys and values have bounded lengths")
        return filters


class AskResponse(BaseModel):
    request_id: str
    answer: str
    confidence: float
    refused: bool
    blocked: bool
    policy_verdicts: list[str]
    citations: list[dict[str, str]]


def build_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    glossary = load_glossary(Path("sample-data/glossary.json"))
    retriever = Retriever(config.index_path, glossary=glossary)
    if config.gateway_mode == "demo":
        gateway = DemoGateway(glossary)
    elif config.gateway_mode == "openai-compatible":
        gateway = OpenAICompatibleGateway(config.model_base_url, config.model_name, config.model_api_key)
    else:
        raise ValueError("RAG_GATEWAY_MODE must be demo or openai-compatible")

    service = RAGService(
        retriever,
        gateway,
        min_confidence=config.min_confidence,
        top_k=config.top_k,
        guardrails=Guardrails() if config.guardrails_enabled else None,
    )
    operations = OperationalLogger(config.runtime_log_path)
    audit = AuditWriter(
        config.audit_log_path,
        pseudonym_salt=config.audit_pseudonym_salt,
        include_prompt=config.audit_include_prompt,
    )
    app = FastAPI(title="Secure LLM Platform Reference", version="0.1.0")

    @app.middleware("http")
    async def limit_request_body(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 64 * 1024:
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        return await call_next(request)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def ready() -> dict[str, str]:
        return {"status": "ready", "index": config.index_path.name}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/ask", response_model=AskResponse)
    def ask(payload: AskRequest, request: Request) -> AskResponse:
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        status = 200
        retrieved_chunks = 0
        refused = True
        verdicts: tuple[str, ...] = ()
        audit_written = False
        actor_id = request.headers.get("x-forwarded-user") or payload.actor_id
        try:
            if config.require_auth_header and not request.headers.get("x-forwarded-user"):
                status = 401
                raise HTTPException(status_code=401, detail="Authenticated proxy header required")
            answer = service.ask(payload.question, filters=payload.filters)
            retrieved_chunks = len(answer.citations)
            refused = answer.refused
            verdicts = answer.policy_verdicts
            for verdict in verdicts:
                POLICY_VERDICTS.labels(verdict=verdict).inc()
            audit.write(
                request_id=request_id,
                actor_id=actor_id,
                question=payload.question,
                confidence=answer.confidence,
                source_ids=[item["source_id"] for item in answer.citations],
                refused=answer.refused,
                policy_verdicts=verdicts,
            )
            audit_written = True
            REQUESTS.labels(status="success", refused=str(answer.refused).lower()).inc()
            return AskResponse(
                request_id=request_id,
                answer=answer.text,
                confidence=round(answer.confidence, 4),
                refused=answer.refused,
                blocked=answer.blocked,
                policy_verdicts=list(verdicts),
                citations=list(answer.citations),
            )
        except HTTPException:
            REQUESTS.labels(status="unauthorized", refused="true").inc()
            raise
        except ValueError as error:
            status = 400
            REQUESTS.labels(status="invalid", refused="true").inc()
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            status = 500
            REQUESTS.labels(status="error", refused="true").inc()
            raise HTTPException(status_code=500, detail="Request failed") from error
        finally:
            if not audit_written:
                try:
                    audit.write(
                        request_id=request_id,
                        actor_id=actor_id,
                        question=payload.question,
                        confidence=0.0,
                        source_ids=[],
                        refused=True,
                    )
                except Exception:
                    REQUESTS.labels(status="audit_error", refused="true").inc()
            elapsed = time.perf_counter() - started
            LATENCY.observe(elapsed)
            operations.write(
                OperationalEvent(
                    timestamp=datetime.now(UTC).isoformat(),
                    request_id=request_id,
                    route="/v1/ask",
                    status_code=status,
                    latency_ms=round(elapsed * 1_000, 2),
                    retrieved_chunks=retrieved_chunks,
                    refused=refused,
                    policy_verdicts=verdicts,
                )
            )

    return app


app = build_app()
