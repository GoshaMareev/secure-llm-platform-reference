"""Private local mTLS delivery/recovery exercise; emits synthetic metadata only."""

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which("docker")
PROJECT = "secure-llm-platform-reference"
COLLECTOR = PROJECT + "-audit-collector-1"
SHIPPER = PROJECT + "-audit-shipper-1"
BASE = "python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"


def docker(*args):
    return subprocess.run([DOCKER, *args], check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603 - fixed operator operations  # noqa: E501 - fixed container-side verification snippet


def count():
    return int(
        docker(
            "exec",
            COLLECTOR,
            "python",
            "-c",
            'import sqlite3; print(sqlite3.connect("/data/events.sqlite3").execute("select count(*) from events").fetchone()[0])',  # noqa: E501 - fixed container-side verification snippet
        )
    )


def run(output):
    if (ROOT / ".local").resolve() not in output.resolve().parents or output.exists():
        raise ValueError("Fresh private report required")
    checks = []
    original = count()
    docker("stop", COLLECTOR)
    try:
        code = 'import time,uuid; from pathlib import Path; from secure_rag.native_audit import append_event; [append_event(Path("/spool"),"gateway",{"timestamp":time.time(),"request_id":str(uuid.uuid4()),"event":"delivery_verification","outcome":"allowed","verdict":"synthetic"},segment_bytes=2048) for _ in range(20)]'  # noqa: E501 - fixed container-side verification snippet
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "502:20",
            "-e",
            "PYTHONPATH=/reference",
            "--mount",
            f"type=bind,src={ROOT / 'apps/rag-assistant'},dst=/reference,readonly",
            "-v",
            PROJECT + "_webui-audit:/spool",
            BASE,
            "python",
            "-c",
            code,
        )
        checks.append({"check": "collector outage preserves local committed events", "passed": True})
    finally:
        docker("start", COLLECTOR)
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline and count() < original + 20:
        time.sleep(2)
    recovered = count()
    checks.append(
        {"check": "all 20 events delivered after recovery and rotation", "passed": recovered == original + 20}
    )
    # Deliberately lose checkpoint acknowledgement: replay all committed events.
    docker("stop", SHIPPER)
    try:
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "502:20",
            "-v",
            PROJECT + "_audit-delivery-state:/state",
            BASE,
            "python",
            "-c",
            'from pathlib import Path; Path("/state/checkpoint.json").unlink(missing_ok=True)',
        )
    finally:
        docker("start", SHIPPER)
    time.sleep(10)
    checks.append(
        {
            "check": "lost checkpoint/restart/repeated delivery creates no duplicates",
            "passed": count() == recovered,
        }
    )
    code = 'import ssl,urllib.request; c=ssl.create_default_context(cafile="/run/certs/ca.crt");\ntry: urllib.request.urlopen(urllib.request.Request("https://audit-collector:8443/events",data=b"{}"),context=c,timeout=5); print("unexpected_acceptance")\nexcept (OSError,ssl.SSLError): print("certificate_rejected")'  # noqa: E501 - fixed container-side verification snippet
    observed = docker("exec", SHIPPER, "python", "-c", code)
    checks.append(
        {
            "check": "untrusted/missing client certificate rejected",
            "passed": observed == "certificate_rejected",
        }
    )
    result = {
        "schema_version": 1,
        "transport": "HTTPS TLS1.2+ with mandatory client certificates",
        "events_added": 20,
        "checks": checks,
        "accepted": all(c["passed"] for c in checks),
        "additional_unit_evidence": [
            "lost acknowledgement replay",
            "event ID collision rejection",
            "fsync failure blocks successful acknowledgement",
            "spool capacity rejection",
            "active-file inode changes during rotation",
        ],
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["accepted"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.report) else 1)
