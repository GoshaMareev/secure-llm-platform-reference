"""Synthetic OpenAI-compatible upstream for gateway boundary verification only."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log incoming messages, even in the synthetic upstream.

    def do_GET(self):  # noqa: N802 - HTTP API
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):  # noqa: N802 - HTTP API
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        incoming = " ".join(str(item.get("content", "")) for item in body.get("messages", []))
        # The upstream records only a Boolean marker in its response. The raw
        # synthetic input must have been masked before it crossed this boundary.
        leaked = any(value in incoming for value in ("demo@northstar.corp", "oncall-owner@", "4111 1111"))
        text = (
            f"Upstream received raw PII: {str(leaked).lower()}. "
            "Emergency access requires approval from the incident commander and one platform owner. "
            "Synthetic output contact: output@northstar.corp."
        )
        result = {
            "id": "synthetic-completion",
            "object": "chat.completion",
            "created": 0,
            "model": "synthetic-reference-model",
            "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        encoded = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104  # internal verification network only
