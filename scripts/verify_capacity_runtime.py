"""Operator-only actual deadline and media admission probes on the isolated gateway."""

import argparse
import base64
import concurrent.futures
import http.client
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from verify_fault_load import ROOT, call, fault


def run(audio, report):
    private = (ROOT / ".local").resolve()
    if private not in audio.resolve().parents or private not in report.resolve().parents or report.exists():
        raise ValueError("Existing private audio and fresh private report required")
    if audio.stat().st_size > 4_000_000:
        raise ValueError("Bounded synthetic WAV required")
    fault()
    connection = http.client.HTTPConnection("127.0.0.1", 4089, timeout=70)
    try:
        connection.putrequest("POST", "/v1/chat/completions")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", "100")
        connection.endheaders()
        connection.send(b'{"messages":[')
        start = time.monotonic()
        response = connection.getresponse()
        data = json.loads(response.read(4096))
        elapsed = time.monotonic() - start
        deadline = {
            "status": response.status,
            "code": data.get("error", {}).get("code"),
            "elapsed_seconds": round(elapsed, 2),
            "passed": response.status == 504
            and data.get("error", {}).get("code") == "request_deadline_exceeded"
            and 59 <= elapsed < 65,
        }
    finally:
        connection.close()
    query = "Summarize the attachment in one sentence."
    encoded = base64.b64encode(audio.read_bytes()).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": query},
                {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}},
            ],
        }
    ]
    barrier = threading.Barrier(2)

    def probe(index):
        barrier.wait(timeout=5)
        row = call(index, query=query, messages=messages, model="reference-multimodal")
        return {key: row[key] for key in ("status", "code", "has_answer", "raw_pii", "latency_ms")}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(probe, range(2)))
    media_passed = sorted(row["status"] for row in rows) == [200, 429] and any(
        row["code"] == "media_capacity_exhausted" for row in rows
    )
    result = {
        "source_commit": subprocess.check_output(  # noqa: S603 - fixed local revision lookup
            [shutil.which("git"), "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "profile": "isolated synthetic upstream; actual local STT; no provider keys",
        "text_deadline": deadline,
        "media_admission": {"checks": rows, "passed": media_passed},
        "accepted": deadline["passed"] and media_passed,
        "scope": "60-second incomplete body and two simultaneous benign WAVs; not a 120-second media soak",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["accepted"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.audio, args.report) else 1)
