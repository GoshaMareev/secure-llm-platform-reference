"""Mandatory LiteLLM policy callback; no retrieval and no prompt logging."""

import asyncio
import hashlib
import hmac
import os
import time
import uuid

import jwt
from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger
from secure_rag.async_work import run_blocking
from secure_rag.decision_guardrails import (
    POLICY_SHA256,
    POLICY_VERSION,
    DecisionClient,
    DecisionUnavailable,
    digest,
    messages_digest,
    validate_state,
)
from secure_rag.guardrails import Guardrails, PiiServiceError
from secure_rag.media_guardrails import (
    ASR_REVISION,
    MAX_MEDIA_PARTS,
    MEDIA_POLICY_VERSION,
    LocalMediaInspector,
    MediaRejected,
)
from secure_rag.native_audit import emit
from secure_rag.presidio_pii import PresidioHttpRedactor
from secure_rag.telemetry import AUDIT_ERRORS, MODEL_ALIAS, REQUEST_CONTEXT, STAGE_SECONDS


class ReferencePolicy(CustomLogger):
    enforces_request_content = True

    def __init__(self):
        super().__init__(turn_off_message_logging=True)
        self.pii = PresidioHttpRedactor()
        self.guardrails = Guardrails(pii=self.pii)
        self.media = LocalMediaInspector(self.pii)
        self.decision_mode = os.environ.get("REFERENCE_DECISION_MODE", "off")
        if self.decision_mode not in {"off", "shadow"}:
            raise ValueError("Decision mode must be off or shadow; enforcement is not calibrated")
        self.decisions = (
            DecisionClient(os.environ["OPENROUTER_API_KEY"]) if self.decision_mode == "shadow" else None
        )
        # Bounded, short-lived private state; never placed in LiteLLM metadata
        # or logs. Output/failure hooks remove it; TTL also covers abandoned calls.
        self._decision_contexts = {}
        self._decision_slots = asyncio.Semaphore(4)

    def record_decision(self, data, event):
        metadata = data["metadata"]
        record = {
            "timestamp": time.time(),
            "event": "semantic_guardrail",
            "request_id": metadata["reference_request_id"],
            "actor_hash": metadata.get("reference_actor_hash", "unknown"),
            "mode": self.decision_mode,
            "corpus_version": metadata.get("reference_corpus_version"),
            "manifest_sha256": metadata.get("reference_manifest_sha256"),
            **event,
        }
        try:
            emit("gateway", "audit", record)
        except OSError:
            AUDIT_ERRORS.labels(component="gateway").inc()
            raise HTTPException(
                503,
                detail={
                    "code": "audit_unavailable",
                    "request_id": metadata["reference_request_id"],
                    "message": "Request unavailable",
                },
            ) from None
        emit("gateway", "runtime", {k: v for k, v in record.items() if k != "actor_hash"})

    async def observe(self, data, stage, state):
        if self.decisions is None:
            return
        start = time.monotonic()
        try:
            if state is None:
                raise DecisionUnavailable("context_unavailable")
            # Bypass backlog rather than turn optional observations into an
            # unbounded queue. Calls have a four-second socket timeout, no retry.
            if self._decision_slots.locked():
                raise DecisionUnavailable("capacity_limit")
            async with self._decision_slots:
                result = await run_blocking(self.decisions.evaluate, stage, state)
            event = result.event(stage)
        except DecisionUnavailable as error:
            event = {
                "stage": stage,
                "status": "unavailable",
                "reason": str(error),
                "policy_version": POLICY_VERSION,
                "policy_sha256": POLICY_SHA256,
                "would_block": None,
            }
        STAGE_SECONDS.labels(stage="jev", model_alias=MODEL_ALIAS.get(), verdict=event["status"]).observe(
            time.monotonic() - start
        )
        self.record_decision(data, event)

    def record(self, data, verdict, outcome, *, media=None):
        metadata = data.setdefault("metadata", {})
        request_id = metadata.setdefault("reference_request_id", str(uuid.uuid4()))
        common = {"timestamp": time.time(), "request_id": request_id, "outcome": outcome, "verdict": verdict}
        if media is not None:
            common["media"] = media
        if metadata.get("reference_blocked_role"):
            common["blocked_role"] = (
                metadata["reference_blocked_role"]
                if metadata["reference_blocked_role"] in {"system", "user", "assistant"}
                else "unknown"
            )
        records = (
            ("runtime", {**common, "event": "model_policy"}),
            (
                "audit",
                {
                    **common,
                    "event": "model_access",
                    "actor_hash": metadata.get("reference_actor_hash", "unknown"),
                    "model_alias": data.get("model")
                    if data.get("model")
                    in {
                        "reference-chat",
                        "reference-vision",
                        "reference-multimodal",
                        "reference-embedding",
                        "reference-rerank",
                    }
                    else "unknown",
                },
            ),
        )
        for channel, record in sorted(records, key=lambda pair: pair[0] != "audit"):
            try:
                emit("gateway", channel, record)
            except OSError:
                AUDIT_ERRORS.labels(component="gateway").inc()
                if REQUEST_CONTEXT.get() is not None:
                    REQUEST_CONTEXT.get()["error_code"] = "audit_unavailable"
                raise HTTPException(
                    503,
                    detail={
                        "message": "Request unavailable",
                        "code": "audit_unavailable",
                        "request_id": request_id,
                    },
                ) from None

    def deny(self, data, verdict, *, media=None, status_code=400):
        if REQUEST_CONTEXT.get() is not None:
            REQUEST_CONTEXT.get()["error_code"] = verdict
        self._decision_contexts.pop(data.get("metadata", {}).get("reference_request_id"), None)
        self.record(data, verdict, "overloaded" if status_code == 429 else "blocked", media=media)
        raise HTTPException(
            status_code,
            detail={
                "message": "Blocked by reference policy",
                "verdict": verdict,
                "code": verdict,
                "request_id": data["metadata"]["reference_request_id"],
            },
        )

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        # Overwrite caller-supplied audit values. Identity comes only from the
        # signed server header, never from metadata or plain user-info headers.
        data.setdefault("metadata", {})["reference_request_id"] = (REQUEST_CONTEXT.get() or {}).get(
            "request_id"
        ) or str(uuid.uuid4())
        data["metadata"].pop("reference_actor_hash", None)
        data["metadata"].pop("reference_blocked_role", None)
        data["metadata"].pop("reference_context_quarantined", None)
        data["metadata"].pop("reference_corpus_version", None)
        data["metadata"].pop("reference_manifest_sha256", None)
        data["metadata"].pop("reference_upstream_started", None)
        data["metadata"]["reference_model_alias"] = data.get("model", "unknown")
        if data.get("model") not in {
            "reference-chat",
            "reference-vision",
            "reference-multimodal",
            "reference-embedding",
            "reference-rerank",
        }:
            self.deny(data, "model_alias_not_allowed")
        MODEL_ALIAS.set(data["model"])
        if any(key in data for key in ("api_base", "api_key", "base_url", "custom_llm_provider")):
            self.deny(data, "provider_override_blocked")
        # LiteLLM strips client-supplied secret_fields before attaching this
        # transport-only mapping. Rerank exposes redacted logging headers in
        # proxy_server_request; authentication must use the raw transport map.
        transport = data.get("secret_fields", {}).get("raw_headers")
        headers = {
            k.lower(): v
            for k, v in (transport or data.get("proxy_server_request", {}).get("headers", {})).items()
        }
        token = headers.get("x-openwebui-user-jwt", "")
        try:
            claims = jwt.decode(
                token,
                os.environ["REFERENCE_IDENTITY_JWT_SECRET"],
                algorithms=["HS256"],
                issuer="open-webui",
                options={"require": ["sub", "iss", "iat", "exp"]},
            )
            if claims.get("role") not in {"user", "admin"}:
                raise ValueError("Unapproved role")
            actor = hmac.new(
                os.environ["REFERENCE_AUDIT_SALT"].encode(), claims["sub"].encode(), hashlib.sha256
            ).hexdigest()[:24]
            data["metadata"]["reference_actor_hash"] = actor
        except (jwt.PyJWTError, KeyError, ValueError, TypeError, AttributeError):
            if not token and call_type in {"embedding", "embeddings", "aembedding"}:
                # Open WebUI embeds Knowledge names/descriptions in a background
                # job without a user. The internal master key authenticates this
                # operation; it never grants chat or document access.
                claims = {"sub": "native-rag-service"}
                data["metadata"]["reference_actor_hash"] = "native-rag-service"
            else:
                self.deny(data, "signed_identity_required")
        context_token = data.pop("reference_context_token", None)
        decision_context = data.pop("reference_decision_context", None)
        if context_token:
            try:
                context = jwt.decode(
                    context_token,
                    os.environ["REFERENCE_IDENTITY_JWT_SECRET"],
                    algorithms=["HS256"],
                    issuer="reference-rag-policy",
                    options={"require": ["sub", "request_id", "iss", "iat", "exp"]},
                )
                if context["sub"] != claims["sub"]:
                    raise ValueError("Identity mismatch")
                if context.get("decision_context_sha256") or decision_context is not None:
                    if digest(decision_context) != context.get("decision_context_sha256"):
                        self.deny(data, "decision_context_mismatch")
                    if messages_digest(data.get("messages", [])) != context.get("messages_sha256"):
                        self.deny(data, "decision_messages_mismatch")
                data["metadata"]["reference_request_id"] = str(uuid.UUID(context["request_id"]))
                if REQUEST_CONTEXT.get() is not None:
                    REQUEST_CONTEXT.get()["request_id"] = data["metadata"]["reference_request_id"]
                data["metadata"]["reference_context_quarantined"] = bool(context.get("quarantined"))
                data["metadata"]["reference_corpus_version"] = context.get("corpus_version")
                data["metadata"]["reference_manifest_sha256"] = context.get("manifest_sha256")
            except (jwt.PyJWTError, KeyError, ValueError, TypeError):
                self.deny(data, "invalid_rag_policy_context")
        if call_type in {"completion", "acompletion"}:
            if not context_token:
                self.deny(data, "rag_policy_context_required")
            if data.get("tools") or data.get("functions"):
                self.deny(data, "unsupported_tools")
            if data.get("audio") or data.get("modalities", ["text"]) != ["text"]:
                self.deny(data, "unsupported_media_output")
            if any(
                data.get(key)
                for key in (
                    "extra_body",
                    "input_audio",
                    "image_url",
                    "video_url",
                    "images",
                    "file",
                    "files",
                    "attachments",
                    "input",
                )
            ):
                self.deny(data, "unsupported_media_input")
            data["max_tokens"] = min(int(data.get("max_tokens") or 1024), 1024)
            # Buffer the complete answer so output checks finish before any
            # token reaches the browser. Request filters enforce this too.
            data["stream"] = False
            data.pop("stream_options", None)
            media_count = 0
            cleaned_media_inputs = []
            for message in data.get("messages", []):
                content = message.get("content", "")
                parts = [{"text": content}] if isinstance(content, str) else content
                for index, part in enumerate(parts or []):
                    if not isinstance(part, dict):
                        self.deny(data, "unsupported_media_input")
                    if part.get("type", "text") != "text":
                        media_count += 1
                        if media_count > MAX_MEDIA_PARTS:
                            self.deny(data, "media_count_limit")
                        try:
                            media_start = time.monotonic()
                            checked = await run_blocking(self.media.check, part)
                            STAGE_SECONDS.labels(
                                stage="ocr" if checked.kind == "image" else "stt",
                                model_alias=data["model"],
                                verdict=checked.verdict,
                            ).observe(time.monotonic() - media_start)
                        except MediaRejected as error:
                            self.deny(
                                data,
                                str(error),
                                media={"policy_version": MEDIA_POLICY_VERSION},
                                status_code=429 if str(error) == "media_capacity_exhausted" else 400,
                            )
                        parts[index] = checked.part
                        if checked.untrusted_text:
                            cleaned_media_inputs.append(checked.untrusted_text)
                        self.record(
                            data,
                            checked.verdict,
                            "allowed",
                            media={
                                "policy_version": MEDIA_POLICY_VERSION,
                                "kind": checked.kind,
                                "asr_revision": ASR_REVISION if checked.kind == "audio" else None,
                                "redacted_kinds": list(checked.redacted_kinds),
                            },
                        )
                        continue
                    decision = await run_blocking(self.guardrails.check_input, part.get("text", ""))
                    if decision.blocked:
                        data["metadata"]["reference_blocked_role"] = message.get("role", "unknown")
                        self.deny(data, decision.verdicts[0])
                    # Drop unrecognized keys: an apparent text part must not
                    # carry an unchecked media payload alongside its text.
                    parts[index] = {"type": "text", "text": decision.text}
                if isinstance(content, str):
                    message["content"] = parts[0]["text"]
                else:
                    message["content"] = parts
                for key in tuple(message):
                    if key not in {"role", "content"}:
                        del message[key]
            if self.decisions is not None:
                now = time.monotonic()
                self._decision_contexts = {
                    key: item for key, item in self._decision_contexts.items() if now - item[0] < 120
                }
                try:
                    if decision_context is not None:
                        validate_state(decision_context)
                        decision_context = {
                            "query": (await run_blocking(self.pii.redact, decision_context["query"]))[0],
                            "untrusted_inputs": cleaned_media_inputs,
                            "passages": [
                                (await run_blocking(self.pii.redact, text))[0]
                                for text in decision_context["passages"]
                            ],
                        }
                    if len(self._decision_contexts) < 128:
                        await self.observe(data, "input_context", decision_context)
                        if decision_context is not None:
                            self._decision_contexts[data["metadata"]["reference_request_id"]] = (
                                now,
                                decision_context,
                            )
                    else:
                        await self.observe(data, "input_context", None)
                except DecisionUnavailable:
                    # Oversized state is explicit unavailable, never truncated.
                    await self.observe(data, "input_context", decision_context)
                except PiiServiceError:
                    self.deny(data, "pii_check_unavailable_blocked")
        elif call_type in {"embedding", "embeddings", "aembedding", "rerank", "arerank"}:
            # Native RAG ingestion, query embedding and reranking all cross the
            # same boundary. Sanitize text before sending it to the provider.
            try:
                for field in ("input", "query", "documents"):
                    if field not in data:
                        continue
                    value = data[field]
                    if isinstance(value, str):
                        data[field] = (await run_blocking(self.pii.redact, value))[0]
                    elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                        data[field] = [(await run_blocking(self.pii.redact, v))[0] for v in value]
                    else:
                        self.deny(data, "unsupported_rag_input")
            except PiiServiceError:
                self.deny(data, "pii_check_unavailable_blocked")
        else:
            self.deny(data, "unsupported_model_operation")
        data["metadata"]["reference_upstream_started"] = time.monotonic()
        return data

    def timing(self, data, verdict):
        started = data.get("metadata", {}).pop("reference_upstream_started", None)
        alias = data.get("metadata", {}).get("reference_model_alias", "unknown")
        if started is not None:
            stage = (
                "retrieval_rerank"
                if alias == "reference-rerank"
                else "retrieval_embedding"
                if alias == "reference-embedding"
                else "upstream_inference"
            )
            STAGE_SECONDS.labels(stage=stage, model_alias=alias, verdict=verdict).observe(
                time.monotonic() - started
            )

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        self.timing(data, "completed")
        saved = self._decision_contexts.pop(data.get("metadata", {}).get("reference_request_id"), None)
        system_prompt = " ".join(
            m["content"]
            for m in data.get("messages", [])
            if m.get("role") == "system" and isinstance(m.get("content"), str)
        )
        output_policy = (
            Guardrails(pii=self.pii, system_prompt=system_prompt) if system_prompt else self.guardrails
        )
        for choice in getattr(response, "choices", []):
            message = getattr(choice, "message", None)
            if message:
                if getattr(message, "tool_calls", None) or getattr(message, "function_call", None):
                    self.deny(data, "unsupported_tool_output")
                if getattr(message, "audio", None) or getattr(message, "images", None):
                    self.deny(data, "unsupported_media_output")
                # Reasoning payloads can contain unscreened text. This demo
                # exposes only the checked final answer.
                for field in (
                    "reasoning_content",
                    "reasoning",
                    "reasoning_details",
                    "annotations",
                    "citations",
                ):
                    if hasattr(message, field):
                        setattr(message, field, None)
                if message.content:
                    output_start = time.monotonic()
                    decision = await run_blocking(output_policy.check_output, message.content)
                    STAGE_SECONDS.labels(
                        stage="output_checks",
                        model_alias=MODEL_ALIAS.get(),
                        verdict="blocked" if decision.blocked else "checked",
                    ).observe(time.monotonic() - output_start)
                    if decision.blocked:
                        self.deny(data, decision.verdicts[0])
                    message.content = decision.text
                    await self.observe(
                        data, "output", {**saved[1], "answer": decision.text} if saved else None
                    )
        verdict = (
            "context_injection_quarantined"
            if data.get("metadata", {}).get("reference_context_quarantined")
            else "model_response_checked"
        )
        self.record(data, verdict, "allowed")
        return response

    async def async_post_call_failure_hook(
        self, request_data, original_exception, user_api_key_dict, traceback_str=None
    ):
        self.timing(request_data, "error")
        self._decision_contexts.pop(request_data.get("metadata", {}).get("reference_request_id"), None)
        # Provider errors can contain input text or internal details. Return a
        # stable error and retain only a verdict in the two event streams.
        if (
            isinstance(original_exception, HTTPException)
            and isinstance(original_exception.detail, dict)
            and (original_exception.detail.get("verdict") or original_exception.detail.get("code"))
        ):
            return original_exception
        self.record(request_data, "model_request_failed", "error")
        return HTTPException(
            502,
            detail={
                "message": "Model request failed",
                "code": "model_request_failed",
                "request_id": request_data["metadata"]["reference_request_id"],
            },
        )

    async def async_post_call_response_headers_hook(self, data, user_api_key_dict, response, **kwargs):
        return {"X-Request-ID": data.get("metadata", {}).get("reference_request_id", "")}

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        # The pinned rerank endpoint omits the proxy post-success hook. Its
        # standard success callback still provides the server-owned metadata.
        if "rerank" in str(kwargs.get("call_type", "")):
            metadata = kwargs.get("litellm_params", {}).get("metadata", {})
            self.timing({"metadata": metadata}, "completed")
            if metadata.get("reference_actor_hash") and metadata.get("reference_request_id"):
                self.record(
                    {"model": metadata.get("reference_model_alias"), "metadata": metadata},
                    "rerank_response_received",
                    "allowed",
                )


policy = ReferencePolicy()
