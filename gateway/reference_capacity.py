"""Bounded ASGI request lifecycle. Installed by an operator-only LiteLLM startup hook."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import Counter

CHAT_PATHS = {"/chat/completions", "/v1/chat/completions"}
MAX_REQUEST_BYTES = 22_000_000
MAX_RESPONSE_BYTES = 1_000_000


class CapacityMiddleware:
    def __init__(self, app, *, capacity=4, text_deadline=60, media_deadline=120, chat_paths=CHAT_PATHS):
        self.app = app
        self.chat_paths = chat_paths
        self.capacity = capacity
        self.text_deadline = text_deadline
        self.media_deadline = media_deadline
        self.active = 0
        self.counts = Counter()
        self.latencies = []

    async def error(self, send, status, code, request_id):
        self.counts[code] += 1
        body = json.dumps(
            {"error": {"code": code, "message": "Request unavailable", "request_id": request_id}}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), (b"x-request-id", request_id.encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"] == "/reference/health":
            from pathlib import Path

            from secure_rag.native_audit import SPOOL_BYTES
            from secure_rag.telemetry import AUDIT_ERRORS, LOG_ERRORS

            try:
                spool = Path("/var/log/reference/audit")
                used = sum(p.stat().st_size for p in spool.glob("*.jsonl"))
                degraded = used >= SPOOL_BYTES or any(
                    v[0] for m in (AUDIT_ERRORS, LOG_ERRORS) for v in list(m.values.values())
                )
            except OSError:
                degraded = True
            body = json.dumps({"status": "degraded" if degraded else "ok", "active": self.active}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 503 if degraded else 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"] == "/reference/metrics":
            from secure_rag.telemetry import render

            body = render() + f"reference_chat_active {self.active}\n".encode()
            for code, count in self.counts.items():
                body += f'reference_chat_requests_total{{verdict="{code}"}} {count}\n'.encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain; version=0.0.4")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        if scope["type"] != "http" or scope["path"] not in self.chat_paths or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        request_id = str(uuid.uuid4())
        from secure_rag.telemetry import REQUEST_CONTEXT

        context = {"request_id": request_id}
        REQUEST_CONTEXT.set(context)
        scope.setdefault("state", {})["reference_request_id"] = request_id
        # No await between checking and reservation: atomic on one event loop.
        if self.active >= self.capacity:
            return await self.error(send, 429, "capacity_exhausted", request_id)
        self.active += 1
        start = time.monotonic()
        worker = monitor = None
        try:
            body = bytearray()
            async with asyncio.timeout(self.text_deadline):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        self.counts["client_cancelled"] += 1
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > MAX_REQUEST_BYTES:
                        return await self.error(send, 413, "request_size_limit", request_id)
                    if not message.get("more_body"):
                        break
            try:
                data = json.loads(body)
                media = any(
                    isinstance(m.get("content"), list)
                    and any(isinstance(p, dict) and p.get("type", "text") != "text" for p in m["content"])
                    for m in data.get("messages", [])
                )
            except (ValueError, TypeError, AttributeError):
                return await self.error(send, 400, "invalid_request", request_id)
            deadline = self.media_deadline if media else self.text_deadline
            remaining = deadline - (time.monotonic() - start)
            queued, total = [], 0
            consumed = False
            disconnected = asyncio.Event()

            async def replay():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                await disconnected.wait()
                return {"type": "http.disconnect"}

            async def capture(message):
                nonlocal total
                total += len(message.get("body", b""))
                if total > MAX_RESPONSE_BYTES:
                    raise ValueError("response_size_limit")
                queued.append(message)

            async def watch_disconnect():
                while True:
                    if (await receive())["type"] == "http.disconnect":
                        disconnected.set()
                        return

            worker = asyncio.create_task(self.app(scope, replay, capture))
            monitor = asyncio.create_task(watch_disconnect())
            done, _ = await asyncio.wait(
                {worker, monitor}, timeout=max(0, remaining), return_when=asyncio.FIRST_COMPLETED
            )
            if worker in done:
                await worker
                response_start = next((m for m in queued if m["type"] == "http.response.start"), None)
                status = response_start["status"] if response_start else 502
                if status >= 400:
                    # Trust only policy state set in this request's server context.
                    # Provider/client error strings cannot manufacture an abstention.
                    code = context.get("error_code", "model_request_failed")
                    self.counts[code] += 1
                    payload = json.dumps(
                        {
                            "error": {
                                "code": code,
                                "message": "Request unavailable",
                                "request_id": context["request_id"],
                            },
                            "detail": {
                                "verdict": code,
                                "message": "Request unavailable",
                                "request_id": context["request_id"],
                            },
                        }
                    ).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": status,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"x-request-id", context["request_id"].encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": payload})
                else:
                    self.counts["completed"] += 1
                    if response_start:
                        response_start["headers"] = [
                            (k, v)
                            for k, v in response_start.get("headers", [])
                            if k.lower() != b"x-request-id"
                        ] + [(b"x-request-id", context["request_id"].encode())]
                    for message in queued:
                        await send(message)
            elif monitor in done:
                self.counts["client_cancelled"] += 1
            else:
                await self.error(send, 504, "request_deadline_exceeded", context["request_id"])
        except TimeoutError:
            await self.error(send, 504, "request_deadline_exceeded", context["request_id"])
        except ValueError:
            await self.error(send, 502, "response_size_limit", context["request_id"])
        except Exception:
            await self.error(send, 502, "model_request_failed", context["request_id"])
        finally:
            # Join cancellation before releasing capacity; no overlapping old job.
            for task in (worker, monitor):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (worker, monitor) if t), return_exceptions=True)
            self.active -= 1
            self.latencies.append(time.monotonic() - start)
            self.latencies = self.latencies[-1000:]


def install():
    from litellm.proxy.proxy_server import app

    app.middleware_stack = CapacityMiddleware(app.middleware_stack)
