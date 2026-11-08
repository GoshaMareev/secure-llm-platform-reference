"""Verify live LiteLLM pre/post-call policy and the RAG HTTP path with a synthetic upstream.

Start the verification profile first (see docs/walkthrough.md). No real inference
or customer data is involved; the test upstream intentionally generates PII.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "rag-assistant")]

from scripts.demo_runtime import ask, demo_settings, running_api  # noqa: E402
from scripts.smoke_presidio import wait_until_ready  # noqa: E402


def main():
    gateway = os.getenv("LITELLM_URL", "http://127.0.0.1:4000").rstrip("/")
    key = os.getenv("LITELLM_MASTER_KEY", "")
    if not key or not wait_until_ready(gateway):
        raise SystemExit("Gateway/key unavailable; start the verification stack as documented")
    headers = {"content-type": "application/json", "authorization": f"Bearer {key}"}
    body = {
        "model": "local-reference-model",
        "messages": [
            {"role": "user", "content": "Reply to demo@northstar.corp about card 4111 1111 1111 1111."},
        ],
    }
    # Do not request any guardrails: default_on must actually protect completion calls.
    request = Request(  # noqa: S310 - local verification gateway
        f"{gateway}/v1/chat/completions", data=json.dumps(body).encode(), headers=headers
    )
    with urlopen(request, timeout=45) as response:  # noqa: S310 - local verification gateway
        answer = json.loads(response.read())["choices"][0]["message"]["content"]
    if "Upstream received raw PII: false" not in answer or "output@northstar.corp" in answer:
        raise SystemExit("Completion pre/post-call policy failed")
    body["messages"][0]["content"] = "My SSN is 219-09-9999."
    try:
        with urlopen(  # noqa: S310 - local verification gateway
            Request(  # noqa: S310 - local verification gateway
                f"{gateway}/v1/chat/completions", data=json.dumps(body).encode(), headers=headers
            ),
            timeout=45,
        ):  # noqa: S310 - local verification gateway
            raise SystemExit("SSN block did not protect the completion route")
    except HTTPError as error:
        if error.code != 400:
            raise SystemExit(f"Unexpected SSN policy HTTP status: {error.code}") from None
    with tempfile.TemporaryDirectory(prefix="reference-gateway-") as directory:
        settings = replace(
            demo_settings(Path(directory)),
            gateway_mode="openai-compatible",
            model_base_url=f"{gateway}/v1",
            model_api_key=key,
            pii_backend="presidio",
        )
        with running_api(settings) as base:
            status, result = ask(base, {"question": "Who can approve emergency production access?"})
            if status != 200 or result["refused"] or "incident commander" not in result["answer"]:
                raise SystemExit("RAG API → LiteLLM → synthetic model failed")
            if "output@northstar.corp" in result["answer"]:
                raise SystemExit("Raw output PII reached the RAG response")
            denied_status, denied = ask(
                base,
                {
                    "question": "Who can approve emergency production access?",
                    "filters": {"audience": "engineers"},
                },
                "reader-demo",
            )
            if denied_status != 200 or not denied["blocked"] or denied["citations"]:
                raise SystemExit("RAG access boundary failed")
    print("PASS: default-on input masking, output masking, SSN block, RAG HTTP path and reader denial")


if __name__ == "__main__":
    main()
