"""Check the running Presidio services and, if started, the LiteLLM Presidio guardrail.

    make presidio-up && make smoke-presidio            # Presidio only
    make gateway-up  && make smoke-presidio            # plus the LiteLLM guardrail

Uses synthetic values only. Exit code 0 means every reachable layer redacted them.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "rag-assistant"))
sys.path.insert(0, str(ROOT))

from secure_rag.presidio_pii import PresidioHttpRedactor  # noqa: E402

SAMPLE = (
    "Dana Whitfield asked to refund GB82 WEST 1234 5698 7654 32, "
    "card 4111 1111 1111 1111, reply to jane.doe@example.com."
)
RAW_VALUES = ("Dana Whitfield", "GB82", "4111 1111", "jane.doe@example.com")


def check(label: str, text: str) -> bool:
    leaked = [value for value in RAW_VALUES if value in text]
    status = "ok  " if not leaked else "FAIL"
    print(f"[{status}] {label}: {text}")
    if leaked:
        print(f"       leaked: {', '.join(leaked)}")
    return not leaked


def wait_until_ready(base_url: str, timeout_seconds: float = 90.0) -> bool:
    """LiteLLM accepts TCP before startup completes; poll readiness instead of racing it."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/health/readiness", timeout=3):  # noqa: S310 - local endpoint
                return True
        except (URLError, ConnectionError, OSError):
            time.sleep(2)
    return False


def main() -> None:
    analyzer = os.getenv("PRESIDIO_ANALYZER_URL", "http://127.0.0.1:5002")
    anonymizer = os.getenv("PRESIDIO_ANONYMIZER_URL", "http://127.0.0.1:5001")
    redacted, kinds = PresidioHttpRedactor(analyzer_url=analyzer, anonymizer_url=anonymizer).redact(SAMPLE)
    passed = check(f"RAG API path via Presidio ({', '.join(kinds)})", redacted)

    gateway = os.getenv("LITELLM_URL", "http://127.0.0.1:4000").rstrip("/")
    key = os.getenv("LITELLM_MASTER_KEY", "")
    try:
        with urlopen(f"{gateway}/health/liveliness", timeout=3):  # noqa: S310 - local endpoint
            pass
    except URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            # Nothing listens on the port: the gateway profile was not started.
            print(f"[skip] LiteLLM gateway not running at {gateway}; start it with make gateway-up")
            raise SystemExit(0 if passed else 1) from None
    except (ConnectionError, OSError):
        pass  # listening but still starting; readiness polling below decides
    if not key:
        print("[FAIL] LITELLM_MASTER_KEY is not set in this shell; export the value the gateway started with")
        raise SystemExit(1)
    if not wait_until_ready(gateway):
        print(f"[FAIL] LiteLLM gateway at {gateway} did not become ready within 90 s")
        raise SystemExit(1)

    request = Request(  # noqa: S310 - local operator endpoint
        f"{gateway}/guardrails/apply_guardrail",
        data=json.dumps({"guardrail_name": "presidio-pii-input", "text": SAMPLE, "language": "en"}).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            body = json.loads(response.read())
        gateway_ok = check("LiteLLM gateway guardrail presidio-pii-input", str(body.get("response_text", body)))
        passed = passed and gateway_ok
    except HTTPError as error:
        print(f"[FAIL] LiteLLM gateway answered HTTP {error.code}: {error.read()[:300]!r}")
        passed = False
    except URLError:
        print(f"[skip] LiteLLM gateway not reachable at {gateway}; start it with make gateway-up")
    except (ConnectionError, OSError) as error:
        # The port answered but the connection dropped: usually the gateway crashed
        # or is still starting. Its logs say which.
        print(f"[FAIL] LiteLLM gateway dropped the connection ({type(error).__name__}).")
        print("       Check: docker compose -f infra/docker-compose.yml logs litellm --tail 100")
        passed = False

    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
