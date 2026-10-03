"""Operator-only dependency/cancellation/audit faults in the isolated synthetic profile."""

import argparse
import base64
import concurrent.futures
import http.client
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from verify_fault_load import ROOT, STATE, URL, call, fault, token

sys.path.insert(0, str(ROOT / "apps/rag-assistant"))
from secure_rag.decision_guardrails import digest, messages_digest  # noqa: E402

DOCKER = shutil.which("docker")
PREFIX = "portfolio-verification-"


def docker(*arguments):
    return subprocess.check_output([DOCKER, *arguments], cwd=ROOT, text=True).strip()  # noqa: S603


def health():
    try:
        with urlopen(URL + "/reference/health", timeout=3) as response:  # noqa: S310 - fixed local endpoint
            return json.load(response)
    except HTTPError as error:
        return json.loads(error.read(1024)) if error.code == 503 else {}
    except Exception:
        return {}


def ready():
    end = time.monotonic() + 90
    while time.monotonic() < end:
        if call()["status"] == 200:
            return True
        time.sleep(1)
    return False


def native_rerank():
    # Operator-created synthetic enrollment; no credentials appear in output.
    code = """import json
from pathlib import Path
from verify import signin,chat
identities=json.loads(Path('/run/secrets/identity-enrollment').read_text())['users']
session,_=signin(next(i['email'] for i in identities if i['scope']=='engineer'))
response=chat(session,'Who approves emergency production access?',model='reference-engineering-rag')
print(json.dumps({'status':response.status_code,'has_answer':bool(response.json().get('choices'))}))
"""
    return json.loads(
        docker("exec", "-e", "PYTHONPATH=/reference", PREFIX + "open-webui-1", "python", "-c", code)
    )


def cancelled():
    now = int(time.time())
    subject = "verification-cancelled-user"
    messages = [{"role": "user", "content": "Which approvers are required for emergency access?"}]
    context = {"query": messages[0]["content"], "passages": []}
    common = {"sub": subject, "iat": now, "exp": now + 300}
    identity = token({**common, "role": "user", "iss": "open-webui"})
    import uuid

    binding = token(
        {
            **common,
            "iss": "reference-rag-policy",
            "request_id": str(uuid.uuid4()),
            "decision_context_sha256": digest(context),
            "messages_sha256": messages_digest(messages),
        }
    )
    body = json.dumps(
        {
            "model": "reference-chat",
            "messages": messages,
            "reference_context_token": binding,
            "reference_decision_context": context,
            "stream": False,
        }
    )
    connection = http.client.HTTPConnection("127.0.0.1", 4089, timeout=10)
    connection.request(
        "POST",
        "/v1/chat/completions",
        body,
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (STATE / "gateway-key").read_text().strip(),
            "X-OpenWebUI-User-JWT": identity,
        },
    )
    end = time.monotonic() + 5
    observed = False
    while time.monotonic() < end:
        if health().get("active", 0) > 0:
            observed = True
            break
        time.sleep(0.05)
    connection.close()
    end = time.monotonic() + 12
    while time.monotonic() < end and health().get("active", 0):
        time.sleep(0.1)
    return observed and health().get("active") == 0


def run(report):
    if (ROOT / ".local").resolve() not in report.resolve().parents or report.exists():
        raise ValueError("Use a fresh private report")
    result = {
        "source_commit": docker_version(),
        "profile": "isolated synthetic verification; no provider credentials",
        "checks": [],
    }
    checks = result["checks"]
    try:
        fault()
        if not ready():
            raise RuntimeError("Isolated preflight failed")
        for service in ("presidio-analyzer", "presidio-anonymizer"):
            docker("stop", PREFIX + service + "-1")
            try:
                row = call(query="Which approvers are required? Contact demo@northstar.corp.")
                checks.append(
                    {
                        "check": service + " unavailable",
                        "status": row["status"],
                        "code": row["code"],
                        "passed": row["status"] >= 400 and not row["has_answer"] and row["correlated_error"],
                    }
                )
            finally:
                docker("start", PREFIX + service + "-1")
                if not ready():
                    raise RuntimeError("PII recovery failed")
        fixture = ROOT / ".local/media-natural-v3/fixtures/image-en-01.png"
        if not fixture.exists():
            fixture = next((ROOT / ".local/media-natural-v3/fixtures").glob("*.png"))
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Summarize this image."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64," + base64.b64encode(fixture.read_bytes()).decode()
                        },
                    },
                ],
            }
        ]
        docker("stop", PREFIX + "media-inspector-1")
        try:
            row = call(query="Summarize this image.", messages=messages, model="reference-vision")
            checks.append(
                {
                    "check": "OCR/STT inspector unavailable",
                    "status": row["status"],
                    "code": row["code"],
                    "passed": row["status"] >= 400 and not row["has_answer"],
                }
            )
        finally:
            docker("start", PREFIX + "media-inspector-1")
        fault("503", "rerank")
        row = native_rerank()
        checks.append(
            {
                "check": "mandatory reranker unavailable",
                **row,
                "passed": row["status"] >= 400 and not row["has_answer"],
            }
        )
        fault()
        marker = "/var/log/reference/audit/verification-full.jsonl"
        docker(
            "exec",
            PREFIX + "litellm-1",
            "python",
            "-c",
            "from pathlib import Path; p=Path("
            + repr(marker)
            + "); p.touch(); p.open('r+b').truncate(100*1024*1024)",
        )
        try:
            row = call()
            checks.append(
                {
                    "check": "audit spool exhausted",
                    "status": row["status"],
                    "code": row["code"],
                    "passed": row["status"] >= 400 and not row["has_answer"],
                }
            )
        finally:
            docker(
                "exec",
                PREFIX + "litellm-1",
                "python",
                "-c",
                "from pathlib import Path; Path(" + repr(marker) + ").unlink(missing_ok=True)",
            )
        docker("restart", PREFIX + "litellm-1")
        checks.append({"check": "gateway process restart recovery", "passed": ready()})
        fault(delay=2000)
        checks.append({"check": "client disconnect releases joined capacity", "passed": cancelled()})
        fault()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(call, range(80)))
        checks.append(
            {
                "check": "mixed synthetic identities bounded/no known PII",
                "passed": all(r["status"] in {200, 429} and not r["raw_pii"] for r in rows)
                and health().get("active") == 0,
                "requests": len(rows),
                "note": "Known-marker check; ownership tested separately by fingerprint suite.",
            }
        )
        result["accepted"] = all(c["passed"] for c in checks)
    finally:
        fault()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    return result.get("accepted", False)


def storage_checks(report):
    if (ROOT / ".local").resolve() not in report.resolve().parents or report.exists():
        raise ValueError("Fresh private report required")
    fault()
    checks = []
    for kind, filename in (
        ("operational", "/var/log/reference/runtime/gateway.runtime.jsonl"),
        ("audit", "/var/log/reference/audit/gateway.audit.jsonl"),
    ):
        docker(
            "exec",
            PREFIX + "litellm-1",
            "python",
            "-c",
            "from pathlib import Path;Path(" + repr(filename) + ").chmod(0o400)",
        )
        try:
            row = call()
            degraded = health().get("status")
            checks.append(
                {
                    "check": kind + " disk write permission failure",
                    "status": row["status"],
                    "code": row["code"],
                    "health": degraded,
                    "passed": (
                        row["status"] == 200
                        if kind == "operational"
                        else row["status"] >= 400 and not row["has_answer"]
                    )
                    and degraded == "degraded",
                }
            )
        finally:
            docker(
                "exec",
                PREFIX + "litellm-1",
                "python",
                "-c",
                "from pathlib import Path;Path(" + repr(filename) + ").chmod(0o600)",
            )
            docker("restart", PREFIX + "litellm-1")
            if not ready():
                raise RuntimeError("Storage fault recovery failed")
    result = {
        "source_commit": docker_version(),
        "checks": checks,
        "accepted": all(c["passed"] for c in checks),
        "scope": (
            "Permission failures on actual disk files; quota exhaustion in separate service suite; "
            "ENOSPC/fsync failure unit injection."
        ),
    }
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["accepted"]


def docker_version():
    return subprocess.check_output([shutil.which("git"), "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()  # noqa: S603


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--storage-only", action="store_true")
    args = parser.parse_args()
    accepted = storage_checks(args.report) if args.storage_only else run(args.report)
    raise SystemExit(0 if accepted else 1)
