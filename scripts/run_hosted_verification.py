"""Operator harness: $5 total preflight and $1 per run; no provider key in WebUI."""

import argparse
import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from provider_budget import remaining

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which("docker")
CONTAINERS = {
    "quality": "secure-llm-platform-reference-open-webui-1",
    "acl": "secure-llm-platform-reference-open-webui-1",
    "media": "secure-llm-platform-reference-open-webui-1",
}
RUNNERS = {
    "quality": "/reference/evaluate.py",
    "acl": "/reference/verify.py",
    "media": "/reference/verify-native-media.py",
}


def run(task, arguments, log):
    used, balance = remaining(ROOT / ".local/openrouter/api-key")
    if balance < 1:
        raise RuntimeError("Insufficient reserved hosted budget")
    container = CONTAINERS[task]
    pid = []
    code = (
        "import os,runpy; print('RUNNER_PID:'+str(os.getpid()),flush=True); runpy.run_path("
        + repr(RUNNERS[task])
        + ",run_name='__main__')"
    )
    revision = subprocess.check_output(  # noqa: S603 - fixed local Git query
        [shutil.which("git"), "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()  # noqa: S603
    hashes = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in [
            "gateway/reference_gateway.py",
            "gateway/reference_capacity.py",
            "apps/rag-assistant/secure_rag/async_work.py",
            "apps/rag-assistant/secure_rag/presidio_pii.py",
            "apps/rag-assistant/secure_rag/media_guardrails.py",
        ]
    }
    command = [
        DOCKER,
        "exec",
        "-e",
        "REFERENCE_SOURCE_COMMIT=" + revision,
        "-e",
        "REFERENCE_RUNTIME_HASHES=" + json.dumps(hashes),
        "--workdir",
        "/app/backend/data",
        container,
        "python",
        "-c",
        code,
        "--live",
        *arguments,
    ]
    with log.open("w") as output:
        process = subprocess.Popen(  # noqa: S603 - operator-only fixed task runner; no shell
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

        def read():
            for line in process.stdout:
                if line.startswith("RUNNER_PID:"):
                    pid.append(int(line.split(":")[1]))
                else:
                    output.write(line)
                    output.flush()

        thread = threading.Thread(target=read)
        thread.start()
        stopped = False
        while process.poll() is None:
            time.sleep(3)
            try:
                current, _ = remaining(ROOT / ".local/openrouter/api-key")
            except Exception:
                current = used + 1  # budget unavailable: stop further calls
            # Reserve $0.05 for the single in-flight, bounded synthetic request.
            if current - used >= 0.95:
                if pid:
                    subprocess.run(  # noqa: S603 - exact worker PID captured from owned process
                        [
                            DOCKER,
                            "exec",
                            container,
                            "python",
                            "-c",
                            f"import os,signal; os.kill({pid[0]},signal.SIGTERM)",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                process.terminate()
                stopped = True
                break
        process.wait()
        thread.join()
    current, _ = remaining(ROOT / ".local/openrouter/api-key")
    measurement = {
        "task": task,
        "cost_usd": round(current - used, 8),
        "total_used_usd": current,
        "run_limit_usd": 1,
        "stopped_by_budget": stopped,
        "exit_code": process.returncode,
    }
    log.with_suffix(".budget.json").write_text(json.dumps(measurement, indent=2) + "\n")
    if current - used > 1:
        raise RuntimeError("Run budget exceeded")
    print(json.dumps(measurement))
    return process.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=RUNNERS)
    parser.add_argument("--log", type=Path, required=True)
    args, arguments = parser.parse_known_args()
    local = (ROOT / ".local").resolve()
    if local not in args.log.resolve().parents:
        raise SystemExit("Logs must remain under .local")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(run(args.task, arguments, args.log))
