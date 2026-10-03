"""Dry-run observations cannot retain originals or escape the local service boundary."""

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/rag-assistant"))
from secure_rag.cloudru_pii import MAX_RESPONSE_BYTES, CloudruScanClient, ScanUnavailable


class ScanClientTests(unittest.TestCase):
    def setUp(self):
        self.response = {
            "masked_texts": ["<EMAIL_1>"],
            "triggered_data_types": [5],
            "placeholders": [{"original": "synthetic@example.test", "placeholder": "<EMAIL_1>"}],
        }
        self.status = 200
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                owner.requests.append((self.path, json.loads(body)))
                self.send_response(owner.status)
                self.send_header("Location", "http://example.com/leak")
                self.end_headers()
                body = owner.response
                self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = CloudruScanClient(f"http://127.0.0.1:{self.server.server_port}")

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_summary_never_retains_or_returns_originals(self):
        texts = ["synthetic@example.test"]
        summary = self.client.scan(texts)
        self.assertEqual(summary.event(), {
            "status": "checked", "text_count": 1, "changed_text_count": 1,
            "match_count": 1, "data_types": [5],
        })
        self.assertNotIn("synthetic", repr(summary))
        self.assertEqual(texts, ["synthetic@example.test"])
        self.assertEqual(self.requests, [("/v1/scan", {"texts": texts})])

    def test_redirect_and_service_error_expose_only_reason_code(self):
        for status in (302, 503):
            self.status = status
            with self.assertRaises(ScanUnavailable) as caught:
                self.client.scan(["synthetic@example.test"])
            self.assertEqual(str(caught.exception), "service_unavailable")

    def test_malformed_and_oversized_responses_are_unavailable(self):
        for body, reason in [
            (b"not JSON: synthetic@example.test", "invalid_response"),
            ({}, "invalid_response"),
            ({**self.response, "masked_texts": []}, "invalid_response"),
            ({**self.response, "triggered_data_types": [True]}, "invalid_response"),
            (b"x" * (MAX_RESPONSE_BYTES + 1), "response_limit"),
        ]:
            self.response = body
            with self.assertRaises(ScanUnavailable) as caught:
                self.client.scan(["synthetic@example.test"])
            self.assertEqual(str(caught.exception), reason)

    def test_input_limit_is_not_silently_truncated(self):
        for texts in ([], ["x"] * 129, ["я" * 262_144]):
            with self.assertRaises(ScanUnavailable) as caught:
                self.client.scan(texts)
            self.assertEqual(str(caught.exception), "input_limit")
        self.assertEqual(self.requests, [])

    def test_only_private_scanner_or_explicit_loopback_is_allowed(self):
        for url in (
            "https://example.com:9080", "http://example.com:9080", "file:///tmp/sample",
            "http://user:secret@cloudru-filter:9080", "http://cloudru-filter:9080/path",
            "http://cloudru-filter:9080?override=1", "http://cloudru-filter",
        ):
            with self.assertRaises(ValueError):
                CloudruScanClient(url)


if __name__ == "__main__":
    unittest.main()
