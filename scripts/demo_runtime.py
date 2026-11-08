"""Loopback-only runtime for synthetic walkthroughs and HTTP integration tests."""

from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import uvicorn
from secure_rag.api import build_app
from secure_rag.settings import Settings

from ingestion.build_index import build
from ingestion.corpus import release
from ingestion.store import write_index


def demo_settings(root: Path) -> Settings:
    index = root / "index.json"
    write_index(
        index, build(Path("sample-data")), source_label="sample-data", corpus=release(Path("sample-data"))
    )
    return Settings(
        index_path=index,
        gateway_mode="demo",
        min_confidence=0.34,
        top_k=3,
        runtime_log_path=root / "runtime" / "runtime.jsonl",
        audit_log_path=root / "audit" / "audit.jsonl",
        audit_include_prompt=False,
        audit_pseudonym_salt="synthetic-walkthrough-key-32-characters",
        model_base_url="http://127.0.0.1:4000/v1",
        model_name="local-reference-model",
        model_api_key="",
        require_auth_header=True,
    )


@contextmanager
def running_api(settings: Settings):
    app = build_app(settings)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    thread.start()
    try:
        for _ in range(100):
            try:
                with urlopen(f"{base}/healthz", timeout=0.5):  # noqa: S310 - bound loopback
                    break
            except (URLError, OSError):
                if not thread.is_alive():
                    raise RuntimeError("Demo API failed to start") from None
                time.sleep(0.02)
        else:
            raise RuntimeError("Demo API readiness timed out")
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def ask(base: str, payload: dict, actor: str | None = "engineer-demo") -> tuple[int, dict]:
    headers = {"content-type": "application/json"}
    if actor is not None:
        headers["x-forwarded-user"] = actor
    request = Request(  # noqa: S310 - loopback test API
        f"{base}/v1/ask", data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - caller uses loopback test server
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())
