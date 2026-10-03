from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator

from ingestion.corpus import release

from .audit import AuditWriter, OperationalEvent, OperationalLogger
from .authorization import IdentityPolicy
from .gateway import DemoGateway, OpenAICompatibleGateway
from .guardrails import Guardrails, build_pii_redactor
from .retrieval import Retriever, load_glossary
from .service import RAGService
from .settings import Settings

REQUESTS = Counter("rag_requests_total", "RAG API requests", ["status", "refused"])
LATENCY = Histogram("rag_request_duration_seconds", "RAG request latency")
POLICY_VERDICTS = Counter("rag_policy_verdicts_total", "Guardrail verdicts by control", ["verdict"])


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4_000)
    filters: dict[str, str] = Field(default_factory=dict)
    actor_id: str = Field(
        default="anonymous",
        min_length=1,
        max_length=128,
        deprecated=True,
        description="Ignored. Identity comes from the trusted proxy or operator configuration.",
    )

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
    corpus_id: str
    corpus_version: str
    manifest_sha256: str
    answer: str
    confidence: float
    refused: bool
    blocked: bool
    policy_verdicts: list[str]
    citations: list[dict[str, str]]


class SessionResponse(BaseModel):
    role: str
    audiences: list[str]
    auth_mode: str
    gateway_mode: str
    guardrails_enabled: bool


def build_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    policy = IdentityPolicy(config.identity_policy_path)
    glossary = load_glossary(Path("sample-data/glossary.json"))
    retriever = Retriever(config.index_path, glossary=glossary)
    if retriever.corpus != release(Path("sample-data")):
        raise ValueError("Index targets different corpus; rebuild it before starting the API")
    if (
        hashlib.sha256(config.identity_policy_path.read_bytes()).hexdigest()
        != (retriever.corpus["auxiliary_sha256"]["identity-policy.json"])
    ):
        raise ValueError("Identity policy differs from the indexed corpus release")
    if config.gateway_mode == "demo":
        gateway = DemoGateway(glossary)
    elif config.gateway_mode == "openai-compatible":
        if not config.guardrails_enabled:
            raise ValueError("External model mode requires guardrails")
        gateway = OpenAICompatibleGateway(
            config.model_base_url,
            config.model_name,
            config.model_api_key,
            allowed_http_hosts=config.model_http_hosts,
        )
    else:
        raise ValueError("RAG_GATEWAY_MODE must be demo or openai-compatible")

    service = RAGService(
        retriever,
        gateway,
        min_confidence=config.min_confidence,
        top_k=config.top_k,
        guardrails=(
            Guardrails(pii=build_pii_redactor(config.pii_backend)) if config.guardrails_enabled else None
        ),
    )
    provenance = {key: retriever.corpus[key] for key in ("corpus_id", "corpus_version", "manifest_sha256")}
    operations = OperationalLogger(config.runtime_log_path)
    audit = AuditWriter(
        config.audit_log_path,
        pseudonym_salt=config.audit_pseudonym_salt,
        include_prompt=config.audit_include_prompt,
    )
    app = FastAPI(title="Secure LLM Platform Reference", version="0.1.0")
    web = Path(__file__).parent / "web"
    app.mount("/demo-assets", StaticFiles(directory=web), name="demo-assets")

    def actor_for(request: Request) -> str:
        return (
            request.headers.get("x-forwarded-user", "")
            if config.require_auth_header
            else config.local_actor_id
        )

    @app.middleware("http")
    async def demo_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path == "/" or request.url.path.startswith("/demo-assets/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    def demo() -> FileResponse:
        return FileResponse(web / "index.html")

    @app.get("/v1/session", response_model=SessionResponse)
    def session(request: Request) -> SessionResponse:
        actor = actor_for(request)
        if config.require_auth_header and not actor:
            raise HTTPException(status_code=401, detail="Authenticated proxy header required")
        try:
            scope = policy.scope_for(actor)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Identity has no access policy") from error
        role = (
            "engineer"
            if "engineers" in scope.audiences
            else ("reader" if scope.audiences == frozenset({"all"}) else "scoped")
        )
        return SessionResponse(
            role=role,
            audiences=sorted(scope.audiences),
            auth_mode="proxy" if config.require_auth_header else "local",
            gateway_mode=config.gateway_mode,
            guardrails_enabled=config.guardrails_enabled,
        )

    @app.middleware("http")
    async def limit_request_body(request: Request, call_next):
        if request.method == "POST":
            content_length = request.headers.get("content-length")
            try:
                length = int(content_length) if content_length else 0
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            if length < 0:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            if length > 64 * 1024:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 64 * 1024:
                    return JSONResponse(status_code=413, content={"detail": "Request body too large"})
            # Starlette's downstream request receives the bounded cached body.
            request._body = bytes(body)
        return await call_next(request)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def ready() -> dict[str, str]:
        return {"status": "ready", "index": config.index_path.name, **provenance}

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
        actor_id = actor_for(request)
        try:
            if config.require_auth_header and not request.headers.get("x-forwarded-user"):
                status = 401
                raise HTTPException(status_code=401, detail="Authenticated proxy header required")
            try:
                scope = policy.scope_for(actor_id)
            except PermissionError as error:
                status = 403
                verdicts = ("identity_access_denied",)
                raise HTTPException(status_code=403, detail="Identity has no access policy") from error
            answer = service.ask(payload.question, filters=payload.filters, scope=scope)
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
                corpus=provenance,
            )
            audit_written = True
            REQUESTS.labels(status="success", refused=str(answer.refused).lower()).inc()
            return AskResponse(
                request_id=request_id,
                **provenance,
                answer=answer.text,
                confidence=round(answer.confidence, 4),
                refused=answer.refused,
                blocked=answer.blocked,
                policy_verdicts=list(verdicts),
                citations=list(answer.citations),
            )
        except HTTPException:
            REQUESTS.labels(status="unauthorized" if status == 401 else "access_denied", refused="true").inc()
            raise
        except ValueError as error:
            status = 400
            REQUESTS.labels(status="invalid", refused="true").inc()
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            refused = True
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
                        policy_verdicts=verdicts,
                        corpus=provenance,
                    )
                except Exception:
                    REQUESTS.labels(status="audit_error", refused="true").inc()
            elapsed = time.perf_counter() - started
            LATENCY.observe(elapsed)
            try:
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
            except OSError:
                REQUESTS.labels(status="operational_log_error", refused=str(refused).lower()).inc()

    return app
