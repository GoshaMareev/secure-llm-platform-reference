"""Validate the resolved optional stack without real credentials or inference."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which("docker")


def model(*, cloudru=False):
    if DOCKER is None:
        raise RuntimeError("Docker is required")
    with tempfile.TemporaryDirectory(prefix="reference-compose-") as directory:
        env_file = Path(directory, "compose.env")
        env_file.write_text(
            f"GOOGLE_SSO_DIR={directory}\nGOOGLE_SSO_UID=1000\nGOOGLE_SSO_GID=1000\n"
            "GOOGLE_OAUTH_CLIENT_ID=synthetic-client\n"
            f"FULL_STACK_DIR={directory}\nFULL_STACK_UID=1000\nFULL_STACK_GID=1000\n"
            f"OPENROUTER_KEY_FILE={directory}/provider-key\n"
        )
        command = [DOCKER, "compose", "--env-file", str(env_file)]
        for name in ("docker-compose.yml", "docker-compose.google.yml", "docker-compose.openwebui.yml"):
            command.extend(["-f", str(ROOT / "infra" / name)])
        if cloudru:
            command.extend(["-f", str(ROOT / "infra/docker-compose.cloudru.yml")])
        command.extend(["--profile", "openwebui", "config", "--format", "json"])
        result = subprocess.run(command, check=True, capture_output=True, env=os.environ)  # noqa: S603
    return json.loads(result.stdout)


def verify():
    config = model()
    services = config["services"]
    webui = services["open-webui"]
    gateway = services["litellm"]
    database = services["webui-postgres"]
    media = services["media-inspector"]
    if (
        media.get("ports")
        or media.get("secrets")
        or set(media["networks"]) != {"platform"}
        or not media.get("read_only")
        or not media.get("mem_limit")
    ):
        raise ValueError("Media inspection must stay private, bounded and without provider credentials")
    for service in (webui, gateway, database):
        if service.get("ports") or "@sha256:" not in service["image"]:
            raise ValueError("Native services must be unpublished and digest-pinned")
    if not config["networks"]["platform"].get("internal") or set(webui["networks"]) != {"platform"}:
        raise ValueError("Web UI must use only the internal platform network")
    webui_secrets = {secret["source"] for secret in webui["secrets"]}
    gateway_secrets = {secret["source"] for secret in gateway["secrets"]}
    if "openrouter-key" in webui_secrets or "openrouter-key" not in gateway_secrets:
        raise ValueError("Provider credential must exist only at the gateway")
    environment = webui["environment"]
    for setting in (
        "ENABLE_DIRECT_CONNECTIONS",
        "ENABLE_SIGNUP",
        "ENABLE_LOGIN_FORM",
        "BYPASS_ADMIN_ACCESS_CONTROL",
        "BYPASS_MODEL_ACCESS_CONTROL",
        "BYPASS_RETRIEVAL_ACCESS_CONTROL",
        "ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS",
        "ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS",
    ):
        if environment[setting] != "false":
            raise ValueError("Native access controls must stay enabled")
    if environment["RAG_EMBEDDING_ENGINE"] != "openai" or environment["RAG_RERANKING_ENGINE"] != "external":
        raise ValueError("Embedding and reranking must use external gateway routes")
    if environment["RAG_OPENAI_API_BASE_URL"] != "http://litellm:4000/v1":
        raise ValueError("Embedding must use the unified gateway")
    proxy = (ROOT / "infra/oauth2-proxy-google-openwebui.cfg").read_text()
    if 'upstreams = ["http://open-webui:8080"]' not in proxy or "skip_auth_strip_headers = true" not in proxy:
        raise ValueError("Proxy must target Web UI and strip caller identity headers")
    print("Full-stack Compose boundaries verified without credentials or hosted calls.")
    pilot = model(cloudru=True)
    scanner = pilot["services"]["cloudru-filter"]
    pilot_gateway = pilot["services"]["litellm"]
    if (
        scanner.get("ports") or scanner.get("secrets") or scanner.get("volumes")
        or "@sha256:" not in scanner["image"] or not scanner.get("read_only")
        or not scanner.get("mem_limit") or set(scanner["networks"]) != {"cloudru-scan"}
        or not pilot["networks"]["cloudru-scan"].get("internal")
    ):
        raise ValueError("Cloud.ru scanner must be private, pinned, bounded and without storage/credentials")
    members = {
        name for name, service in pilot["services"].items() if "cloudru-scan" in service.get("networks", {})
    }
    if members != {"cloudru-filter", "litellm"}:
        raise ValueError("Only the gateway may reach the scanner management plane")
    if (
        pilot_gateway["environment"]["REFERENCE_CLOUDRU_MODE"] != "shadow"
        or pilot_gateway["environment"]["REFERENCE_CLOUDRU_SCAN_URL"] != "http://cloudru-filter:9080"
        or scanner["environment"]["GUARDRAILS_AUDIT_ENABLED"] != "false"
        or scanner["environment"]["GUARDRAILS_UI_ENABLED"] != "false"
        or scanner["environment"]["GUARDRAILS_STORE_BACKEND"] != "in_memory"
        or scanner["environment"]["GUARDRAILS_UPSTREAM_BASE_URL"] != "http://127.0.0.1:1"
    ):
        raise ValueError("Cloud.ru pilot must remain a local, non-persistent shadow scan")
    print("Optional Cloud.ru shadow scan boundaries verified.")


if __name__ == "__main__":
    verify()
