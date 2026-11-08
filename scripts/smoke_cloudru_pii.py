"""Exercise gateway callbacks with live local Presidio/Cloud.ru, without model inference."""

import asyncio
import json
import os
import secrets
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway"), str(ROOT / "apps/rag-assistant")]
# Synthetic callback identity; never load an operator or provider credential.
os.environ["REFERENCE_DECISION_MODE"] = "off"
os.environ["REFERENCE_IDENTITY_JWT_SECRET"] = secrets.token_hex(32)
os.environ["REFERENCE_AUDIT_SALT"] = "synthetic-cloudru-smoke-salt"

import jwt  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from reference_gateway import ReferencePolicy  # noqa: E402
from secure_rag.cloudru_pii import CloudruScanClient  # noqa: E402


def token(issuer, **extra):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer,
            "sub": "synthetic-cloudru-smoke",
            "role": "user",
            "iat": now,
            "exp": now + 60,
            **extra,
        },
        os.environ["REFERENCE_IDENTITY_JWT_SECRET"],
        algorithm="HS256",
    )


async def main():
    policy = ReferencePolicy()
    if policy.cloudru is None:
        raise SystemExit("Cloud.ru shadow mode is not enabled")
    events = []
    write_event = policy.record_decision

    def capture(data, event):
        events.append(event)
        write_event(data, event)

    policy.record_decision = capture
    sample = "-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n-----END PRIVATE KEY-----"
    data = {
        "model": "reference-chat",
        "messages": [{"role": "user", "content": sample}],
        "secret_fields": {"raw_headers": {"X-OpenWebUI-User-JWT": token("open-webui")}},
        "reference_context_token": token("reference-rag-policy", request_id=str(uuid.uuid4())),
    }
    await policy.async_pre_call_hook(None, None, data, "completion")
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=sample))])
    await policy.async_post_call_success_hook(data, None, response)
    if len(events) != 2 or any(event["status"] != "checked" or event["match_count"] < 1 for event in events):
        raise SystemExit("Live callback scan did not observe both stages")
    if "SYNTHETIC" in repr(events) or "PRIVATE KEY" in repr(events):
        raise SystemExit("Observation contains sample text")
    checks = [{"id": "input_output_and_private_audit", "passed": True}]
    for call_type, request in (
        ("embedding", {"model": "reference-embedding", "input": [sample]}),
        ("rerank", {"model": "reference-rerank", "query": "Approved policy", "documents": [sample]}),
    ):
        request["secret_fields"] = {"raw_headers": {"X-OpenWebUI-User-JWT": token("open-webui")}}
        start = len(events)
        await policy.async_pre_call_hook(None, None, request, call_type)
        if len(events) != start + 1 or events[-1]["status"] != "checked" or events[-1]["match_count"] < 1:
            raise SystemExit("Embedding/rerank scan failed")
        checks.append({"id": call_type + "_scan", "passed": True})

    scanner = policy.cloudru
    policy.cloudru = CloudruScanClient("http://127.0.0.1:1")
    request = {"model": "reference-embedding", "input": "Contact synthetic@example.test"}
    await policy.async_pre_call_hook(None, None, request, "embedding")
    if events[-1]["reason"] != "service_unavailable" or "@" in request["input"]:
        raise SystemExit("Scanner outage weakened mandatory privacy checks")
    checks.append({"id": "scanner_outage_preserves_presidio", "passed": True})
    policy.cloudru = scanner

    slots = policy._cloudru_slots
    policy._cloudru_slots = asyncio.Semaphore(0)
    await policy.async_pre_call_hook(
        None, None, {"model": "reference-embedding", "input": sample}, "embedding"
    )
    if events[-1]["reason"] != "capacity_limit":
        raise SystemExit("Capacity limit not observed")
    policy._cloudru_slots = slots
    checks.append({"id": "capacity_limit", "passed": True})

    await policy.async_pre_call_hook(
        None, None, {"model": "reference-embedding", "input": ["Approved gateway."] * 129}, "embedding"
    )
    if events[-1]["reason"] != "input_limit":
        raise SystemExit("Oversized scan was silently truncated")
    checks.append({"id": "text_count_limit", "passed": True})

    start = len(events)
    try:
        await policy.async_pre_call_hook(
            None,
            None,
            {"model": "reference-chat", "messages": [{"role": "user", "content": sample}]},
            "completion",
        )
        raise SystemExit("Unsigned identity was accepted")
    except HTTPException as error:
        if error.detail["verdict"] != "signed_identity_required" or len(events) != start:
            raise SystemExit("Unauthorized input reached the scanner") from None
    checks.append({"id": "unsigned_identity_denied_before_scan", "passed": True})
    if any(value in repr(events) for value in ("SYNTHETIC", "PRIVATE KEY", "synthetic@example.test")):
        raise SystemExit("Observation contains sample text")
    print(
        json.dumps(
            {
                "scope": "Live direct gateway callbacks and local services; no model inference",
                "passed": len(checks),
                "total": len(checks),
                "checks": checks,
                "audit_events": len(events),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
