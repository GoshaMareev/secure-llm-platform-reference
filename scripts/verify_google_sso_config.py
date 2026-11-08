"""Validate the merged Google stack with synthetic credentials and the pinned proxy."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from google_sso import CALLBACK, ROOT, initialize


def main() -> None:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker is required")
    (ROOT / ".local").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".local") as temporary:
        base = Path(temporary)
        client = base / "client.json"
        client.write_text(
            json.dumps(
                {
                    "web": {
                        "client_id": "0000-synthetic.apps.googleusercontent.com",
                        "client_secret": "synthetic-only",
                        "redirect_uris": [CALLBACK],
                    }
                }
            )
        )
        directory = base / "private"
        initialize(client, directory, ["synthetic@example.test"])
        command = [
            docker,
            "compose",
            "--env-file",
            str(directory / "compose.env"),
            "-f",
            str(ROOT / "infra/docker-compose.yml"),
            "-f",
            str(ROOT / "infra/docker-compose.google.yml"),
        ]
        result = subprocess.run(  # noqa: S603 - resolved Docker executable, fixed Compose files
            [*command, "config", "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        model = json.loads(result.stdout)
        proxy = model["services"]["oauth2-proxy"]
        if set(proxy["environment"]) != {"OAUTH2_PROXY_CLIENT_ID"}:
            raise RuntimeError("Google inherited provider settings or credentials in environment")
        if any(port["host_ip"] != "127.0.0.1" for port in proxy["ports"]):
            raise RuntimeError("Google proxy must bind only to loopback")
        if model["services"]["rag-assistant"].get("ports"):
            raise RuntimeError("The protected API must not publish a port")
        subprocess.run(  # noqa: S603 - pinned proxy performs configuration validation
            [
                *command,
                "run",
                "--rm",
                "--no-deps",
                "oauth2-proxy",
                "--config",
                "/etc/oauth2-proxy/google.cfg",
                "--config-test",
            ],
            check=True,
        )
    print("Merged Google stack and pinned OAuth2 Proxy configuration passed (synthetic credentials).")


if __name__ == "__main__":
    main()
