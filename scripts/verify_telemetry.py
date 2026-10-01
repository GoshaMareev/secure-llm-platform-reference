"""Verify a synthetic container API event in Loki and the separate audit spool."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

DOCKER = shutil.which("docker")
if DOCKER is None:
    raise RuntimeError("Docker executable not found")
COMPOSE = [DOCKER, "compose", "-f", "infra/docker-compose.yml"]
PROBE = """
import json
from pathlib import Path
from urllib.request import Request, urlopen
request = Request('http://127.0.0.1:8000/v1/ask',
    data=json.dumps({'question':'Who can approve emergency production access?'}).encode(),
    headers={'content-type':'application/json','x-forwarded-user':'engineer-demo'})
with urlopen(request, timeout=30) as response:
    body = json.loads(response.read())
events = []
for path in ['/var/log/reference/runtime/runtime.jsonl', '/var/log/reference/audit/audit.jsonl']:
    events.append(next(json.loads(line) for line in Path(path).read_text().splitlines()
                       if json.loads(line)['request_id'] == body['request_id']))
print(json.dumps({'request_id':body['request_id'], 'events':events}))
"""


def main():
    result = subprocess.run(  # noqa: S603 - fixed Docker command and synthetic probe
        [*COMPOSE, "exec", "-T", "rag-assistant", "python", "-c", PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    probe = json.loads(result.stdout)
    op, audit = probe["events"]
    if "prompt" in op or "answer" in op or "prompt" in audit:
        raise SystemExit("Unexpected raw content in the default log streams")
    container_id = subprocess.check_output(  # noqa: S603 - fixed Compose arguments
        [*COMPOSE, "ps", "-q", "fluent-bit"], text=True
    ).strip()
    if re.fullmatch(r"[0-9a-f]{12,64}", container_id) is None:
        raise RuntimeError("Invalid collector container ID")
    inspection = subprocess.check_output([DOCKER, "inspect", container_id], text=True)  # noqa: S603
    config = json.loads(inspection)[0]
    if config["Config"]["User"] != "10001:10001":
        raise SystemExit("Collector must run as the log owner's unprivileged UID")
    if any(mount["Name"].endswith("audit-spool") for mount in config["Mounts"] if mount.get("Name")):
        raise SystemExit("Collector unexpectedly has access to the audit volume")
    base = os.getenv("LOKI_URL", "http://127.0.0.1:3100").rstrip("/")
    params = urlencode(
        {
            "query": '{job="secure-llm-reference",stream="operational"} |= "' + probe["request_id"] + '"',
            "limit": 10,
        }
    )
    for _ in range(30):
        try:
            with urlopen(f"{base}/loki/api/v1/query_range?{params}", timeout=2) as response:  # noqa: S310
                streams = json.loads(response.read())["data"]["result"]
            for stream in streams:
                for _, line in stream["values"]:
                    event = json.loads(line)
                    if event["request_id"] == probe["request_id"]:
                        if "prompt" in event or "answer" in event:
                            raise SystemExit("Loki received raw prompt/answer content")
                        print(
                            "PASS: container request ID correlated in Loki and audit; "
                            "collector has no audit mount"
                        )
                        return
        except (URLError, OSError):
            pass
        time.sleep(1)
    raise SystemExit("Operational event did not reach Loki within 30 seconds")


if __name__ == "__main__":
    main()
