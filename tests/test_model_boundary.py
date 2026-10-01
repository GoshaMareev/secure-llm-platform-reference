from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "rag-assistant")]

from secure_rag.authorization import RetrievalScope  # noqa: E402
from secure_rag.gateway import MAX_RESPONSE_BYTES, OpenAICompatibleGateway  # noqa: E402
from secure_rag.guardrails import Guardrails, PiiServiceError  # noqa: E402
from secure_rag.retrieval import Retriever  # noqa: E402
from secure_rag.service import RAGService  # noqa: E402

from scripts.demo_runtime import ask, demo_settings, running_api  # noqa: E402


class ModelHandler(BaseHTTPRequestHandler):
    mode = "answer"
    requests: list[dict] = []

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802 - HTTP API
        type(self).requests.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
        if self.mode == "redirect":
            self.send_response(307)
            self.send_header("location", "/other-model")
            self.end_headers()
            return
        content = json.dumps({"choices": [{"message": {"content": "Contact model-output@northstar.corp."}}]})
        if self.mode == "large":
            content = "x" * (MAX_RESPONSE_BYTES + 1)
        encoded = content.encode()
        self.send_response(200)
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The bounded client intentionally closes an oversized response.


class ModelBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = demo_settings(Path(self.temporary.name))
        ModelHandler.mode = "answer"
        ModelHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_raw_context_pii_is_removed_before_http_and_generated_pii_before_response(self):
        config = replace(self.settings, gateway_mode="openai-compatible", model_base_url=self.base)
        with running_api(config) as base:
            status, result = ask(base, {"question": "How do I contact the on-call platform owner?"})
        self.assertEqual(status, 200)
        outbound = json.dumps(ModelHandler.requests)
        self.assertNotIn("oncall-owner@", outbound)
        self.assertNotIn("555 0143", outbound)
        self.assertIn("[REDACTED_EMAIL]", outbound)
        self.assertNotIn("model-output@", result["answer"])
        self.assertIn("context_pii_redacted", result["policy_verdicts"])
        self.assertIn("output_pii_redacted", result["policy_verdicts"])

    def test_context_pii_outage_blocks_generation(self):
        class ContextUnavailable:
            calls = 0

            def redact(self, text):
                self.calls += 1
                if self.calls > 1:
                    raise PiiServiceError("synthetic unavailable")
                return text, ()

        service = RAGService(
            Retriever(self.settings.index_path),
            OpenAICompatibleGateway(self.base, "model", ""),
            min_confidence=0.34,
            top_k=3,
            guardrails=Guardrails(pii=ContextUnavailable()),
        )
        answer = service.ask(
            "Who can approve emergency production access?",
            scope=RetrievalScope(frozenset({"all", "engineers"})),
        )
        self.assertTrue(answer.blocked)
        self.assertIn("pii_check_unavailable_blocked", answer.policy_verdicts)
        self.assertEqual(ModelHandler.requests, [])

    def test_redirect_cannot_move_context_or_credentials_to_another_route(self):
        ModelHandler.mode = "redirect"
        with self.assertRaises(HTTPError):
            OpenAICompatibleGateway(self.base, "model", "synthetic-key").answer("question", [])
        self.assertEqual(len(ModelHandler.requests), 1)

    def test_large_model_response_is_bounded(self):
        ModelHandler.mode = "large"
        with self.assertRaisesRegex(ValueError, "size limit"):
            OpenAICompatibleGateway(self.base, "model", "").answer("question", [])

    def test_internal_http_requires_explicit_operator_allowlist(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleGateway("http://litellm:4000/v1", "model", "")
        OpenAICompatibleGateway("http://litellm:4000/v1", "model", "", allowed_http_hosts=("litellm",))

    def test_external_model_cannot_disable_guardrails(self):
        with self.assertRaisesRegex(ValueError, "requires guardrails"):
            with running_api(
                replace(self.settings, gateway_mode="openai-compatible", guardrails_enabled=False)
            ):
                pass

    def test_failed_audit_prevents_answer_delivery(self):
        with patch("secure_rag.api.AuditWriter.write", side_effect=OSError("synthetic audit unavailable")):
            with running_api(self.settings) as base:
                status, result = ask(base, {"question": "Who can approve emergency production access?"})
        self.assertEqual(status, 500)
        self.assertNotIn("answer", result)
