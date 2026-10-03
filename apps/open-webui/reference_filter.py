"""
title: Reference RAG policy
version: 0.1.0
description: Mandatory checks around native Knowledge retrieval; no custom retrieval.
"""

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid

import jwt
from fastapi import HTTPException
from secure_rag.guardrails import (
    CONTEXT_ONLY_RULES,
    EXFILTRATION_RULES,
    INJECTION_RULES,
    Guardrails,
    PiiServiceError,
    _matches,
)
from secure_rag.presidio_pii import PresidioHttpRedactor


class Filter:
    # No toggle or UserValves: regular users cannot disable this global filter.
    def __init__(self):
        self.pii = PresidioHttpRedactor()
        self.guardrails = Guardrails(pii=self.pii)

    async def inlet(self, body, __user__, __metadata__, __model__, __request__):
        from reference_rerank import bind

        bind(__request__, __user__)
        request_id = str(uuid.uuid4())
        __metadata__["reference_request_id"] = request_id
        meta = (__model__.get("info") or {}).get("meta") or {}
        grounded = bool(meta.get("reference_grounded"))
        if grounded:
            # The operator's model fixes the collection scope and retrieval
            # mode. A client cannot remove Knowledge or switch to tool-only RAG.
            body["files"] = [dict(item) for item in meta.get("knowledge", [])]
            __metadata__.setdefault("params", {})["function_calling"] = "legacy"
            body["tools"] = []
            body.pop("tool_ids", None)
            body.pop("features", None)
            body["messages"] = [m for m in body.get("messages", []) if m.get("role") != "system"]
        __metadata__["reference_requires_evidence"] = grounded or bool(body.get("files"))
        for message in body.get("messages", []):
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            parts = [{"type": "text", "text": content}] if isinstance(content, str) else content
            for part in parts or []:
                if part.get("type") != "text":
                    continue
                decision = await asyncio.to_thread(self.guardrails.check_input, part.get("text", ""))
                if decision.blocked:
                    self.deny(__user__, request_id, decision.verdicts[0])
                part["text"] = decision.text
            if isinstance(content, str):
                message["content"] = parts[0]["text"]
        body["stream"] = False
        body.pop("stream_options", None)
        return body

    async def request(self, body, __user__, __metadata__, __request__, __event_emitter__=None):
        from open_webui.utils.middleware import apply_source_context_to_messages

        request_id = __metadata__.get("reference_request_id") or str(uuid.uuid4())
        sources = __metadata__.get("sources", [])
        if __metadata__.get("reference_requires_evidence") and not sources:
            self.deny(__user__, request_id, "no_safe_evidence")
        ranking = getattr(__request__.state, "reference_rerank", {})
        if sources and (ranking.get("failed") or not ranking.get("completed")):
            self.deny(__user__, request_id, "external_rerank_required")
        accepted = []
        quarantined = False
        try:
            for source in sources:
                docs = source.get("document", [])
                metadata = source.get("metadata", [])
                kept_docs, kept_metadata, kept_distances = [], [], []
                for index, text in enumerate(docs):
                    if _matches(text, (*INJECTION_RULES, *EXFILTRATION_RULES, *CONTEXT_ONLY_RULES)):
                        quarantined = True
                        continue
                    kept_docs.append((await asyncio.to_thread(self.pii.redact, text))[0])
                    if index < len(source.get("distances", [])):
                        kept_distances.append(source["distances"][index])
                    item = metadata[index] if index < len(metadata) else {}
                    kept_metadata.append(
                        {
                            k: (await asyncio.to_thread(self.pii.redact, v))[0] if isinstance(v, str) else v
                            for k, v in item.items()
                        }
                    )
                # Mutate shared citation objects, so the response event and the
                # provider prompt both use the same screened document text.
                source["document"] = kept_docs
                source["metadata"] = kept_metadata
                source["distances"] = kept_distances
                source["source"] = {
                    k: (await asyncio.to_thread(self.pii.redact, v))[0] if isinstance(v, str) else v
                    for k, v in source.get("source", {}).items()
                }
                if kept_docs:
                    accepted.append(source)
                else:
                    source["source"] = {}
        except PiiServiceError:
            self.deny(__user__, request_id, "pii_check_unavailable_blocked")
        if sources:
            prompt = __metadata__.get("user_prompt", "")
            # Open WebUI's add_or_update_user_message(append=False) PREPENDS
            # rather than replaces. Discard the previous unfiltered RAG copy.
            for message in reversed(body["messages"]):
                if message.get("role") == "user":
                    message["content"] = prompt
                    break
            if not accepted:
                self.deny(__user__, request_id, "no_safe_evidence")
            body["messages"] = await apply_source_context_to_messages(
                __request__, body["messages"], accepted, prompt
            )
        # A server-signed context transfers the request ID across OpenAI's
        # metadata stripping step. LiteLLM consumes it before provider routing.
        now = int(time.time())
        body["reference_context_token"] = jwt.encode(
            {
                "sub": __user__["id"],
                "request_id": request_id,
                "iss": "reference-rag-policy",
                "iat": now,
                "exp": now + 300,
                "quarantined": quarantined,
            },
            os.environ["REFERENCE_IDENTITY_JWT_SECRET"],
            algorithm="HS256",
        )
        body["stream"] = False
        body.pop("stream_options", None)
        verdict = "context_injection_quarantined" if quarantined else "rag_context_checked"
        self.record(__user__, request_id, verdict, "allowed")
        if __event_emitter__:
            # v0.11.4's buffered WebSocket path emits completion before it
            # merges HTTP source events. Publish only screened citations via
            # its native source event so the browser can open the evidence.
            for source in accepted:
                await __event_emitter__({"type": "source", "data": source})
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "action": "reference_policy",
                        "description": "Sources checked · Request ID: " + request_id,
                        "done": True,
                    },
                }
            )
        return body

    def deny(self, user, request_id, verdict):
        self.record(user, request_id, verdict, "blocked")
        raise HTTPException(
            400,
            detail={
                "message": "Blocked by reference RAG policy",
                "verdict": verdict,
                "request_id": request_id,
            },
        )

    def record(self, user, request_id, verdict, outcome):
        actor = hmac.new(
            os.environ["REFERENCE_AUDIT_SALT"].encode(), user["id"].encode(), hashlib.sha256
        ).hexdigest()[:24]
        common = {
            "timestamp": time.time(),
            "request_id": request_id,
            "outcome": outcome,
            "verdict": verdict,
        }
        for channel, event in (
            ("runtime", {**common, "event": "rag_policy"}),
            ("audit", {**common, "event": "rag_access", "actor_hash": actor}),
        ):
            fd = os.open(
                f"/var/log/reference/{channel}/{channel}.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
            )
            try:
                os.write(fd, (json.dumps(event) + "\n").encode())
            finally:
                os.close(fd)
