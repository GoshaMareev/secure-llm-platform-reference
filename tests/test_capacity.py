"""Exercise concurrent admission, deadlines, disconnect and bounded responses."""

import asyncio
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "gateway"),
    str(Path(__file__).resolve().parents[1] / "apps/rag-assistant"),
]
from reference_capacity import CapacityMiddleware  # noqa: E402 - local module path


class CapacityTests(unittest.IsolatedAsyncioTestCase):
    def request(self, middleware, disconnect=None):
        queue = asyncio.Queue()
        queue.put_nowait({"type": "http.request", "body": b'{"messages":[]}'})
        sent = []

        async def receive():
            if disconnect and queue.empty():
                await disconnect.wait()
                return {"type": "http.disconnect"}
            return await queue.get()

        return middleware(
            {"type": "http", "path": "/v1/chat/completions", "method": "POST"}, receive, lambda_message(sent)
        ), sent

    async def test_full_capacity_has_no_queue_and_cancellation_releases_it(self):
        gate = asyncio.Event()

        async def app(scope, receive, send):
            await gate.wait()

        middleware = CapacityMiddleware(app)
        tasks = [asyncio.create_task(self.request(middleware)[0]) for _ in range(4)]
        await asyncio.sleep(0.01)
        call, sent = self.request(middleware)
        await call
        self.assertEqual(sent[0]["status"], 429)
        self.assertEqual(json.loads(sent[1]["body"])["error"]["code"], "capacity_exhausted")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(middleware.active, 0)

    async def test_deadline_cancels_and_joins_work(self):
        ended = asyncio.Event()

        async def app(scope, receive, send):
            try:
                await asyncio.sleep(100)
            finally:
                ended.set()

        middleware = CapacityMiddleware(app, text_deadline=0.01)
        call, sent = self.request(middleware)
        await call
        self.assertEqual(sent[0]["status"], 504)
        self.assertTrue(ended.is_set())
        self.assertEqual(middleware.active, 0)

    async def test_client_disconnect_releases_capacity_without_answer(self):
        async def app(scope, receive, send):
            await asyncio.sleep(100)

        event = asyncio.Event()
        m = CapacityMiddleware(app)
        call, sent = self.request(m, event)
        task = asyncio.create_task(call)
        await asyncio.sleep(0.01)
        event.set()
        await task
        self.assertEqual(sent, [])
        self.assertEqual(m.active, 0)

    async def test_oversized_model_answer_never_reaches_client(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"x" * 1_000_001})

        m = CapacityMiddleware(app)
        call, sent = self.request(m)
        await call
        self.assertEqual(sent[0]["status"], 502)
        self.assertLess(len(sent[1]["body"]), 300)

    async def test_cancelled_blocking_work_keeps_capacity_until_joined(self):
        from secure_rag.async_work import run_blocking

        ended = threading.Event()
        entered = threading.Event()

        def blocking():
            entered.set()
            ended.wait(2)

        async def app(scope, receive, send):
            await run_blocking(blocking)

        middleware = CapacityMiddleware(app, text_deadline=0.03)
        call, sent = self.request(middleware)
        worker = asyncio.create_task(call)
        await asyncio.sleep(0.07)
        self.assertTrue(entered.is_set())
        self.assertEqual(sent[0]["status"], 504)
        self.assertEqual(middleware.active, 1)
        ended.set()
        await worker
        self.assertEqual(middleware.active, 0)


def lambda_message(sent):
    async def send(message):
        sent.append(message)

    return send
