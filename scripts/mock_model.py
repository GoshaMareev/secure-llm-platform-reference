"""Synthetic OpenAI-compatible upstream for gateway boundary verification only."""

from __future__ import annotations

import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log incoming messages, even in the synthetic upstream.

    def do_GET(self):  # noqa: N802 - HTTP API
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):  # noqa: N802 - HTTP API
        length = int(self.headers.get("content-length", "0"))
        if not 0 < length <= 22_000_000:
            self.send_error(413)
            return
        body = json.loads(self.rfile.read(length))
        operation = "embedding" if "embedding" in self.path else "rerank" if "rerank" in self.path else "chat"
        config_file = os.environ.get("VERIFICATION_FAULT_FILE")
        config = json.loads(Path(config_file).read_text()) if config_file else {"mode": "normal"}
        selected = config.get("operation", "all") in {"all", operation}
        mode = config.get("mode", "normal") if selected else "normal"
        time.sleep(min(120, max(0, float(config.get("delay_ms", 0)) / 1000)))
        if mode in {"429", "500", "503"}:
            self.send_response(int(mode))
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"synthetic fault","type":"verification"}}')
            return
        if mode == "disconnect":
            self.close_connection = True
            return
        if mode == "timeout":
            time.sleep(65)
            return
        if mode == "invalid_json":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{bad json")
            return
        if operation == "embedding":
            inputs = body.get("input", [])
            inputs = [inputs] if isinstance(inputs, str) else inputs
            from ingestion.vectorizer import tokenize, vectorize

            result = {
                "object": "list",
                "model": "verification-embedding",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
                "data": [
                    {
                        "object": "embedding",
                        "index": i,
                        "embedding": [*vectorize(tokenize(text)), *([0.0] * 1440)],
                    }
                    for i, text in enumerate(inputs)
                ],
            }
            return self.reply(result)
        if operation == "rerank":
            from ingestion.vectorizer import tokenize

            query = set(tokenize(body["query"]))
            documents = body["documents"]
            scores = [
                len(query & set(tokenize(d if isinstance(d, str) else d["text"]))) / max(1, len(query))
                for d in documents
            ]
            ranked = sorted(range(len(documents)), key=lambda i: (-scores[i], i))[
                : body.get("top_n", len(documents))
            ]
            return self.reply(
                {
                    "id": "verification-rerank",
                    "results": [{"index": i, "relevance_score": scores[i]} for i in ranked],
                    "meta": {"billed_units": {"search_units": 1}},
                }
            )
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
            "system_fingerprint": "verification-" + hashlib.sha256(incoming.encode()).hexdigest(),
            "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        if mode == "large_response":
            result["choices"][0]["message"]["content"] = "x" * 1_000_001
        return self.reply(result)

    def reply(self, result):
        encoded = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104  # internal verification network only
