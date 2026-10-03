"""Read private file mounts before launching the official service entrypoint."""

import os
import sys
from pathlib import Path


def load(name: str, filename: str) -> None:
    value = Path("/run/secrets", filename).read_text().strip()
    if not value or "\n" in value:
        raise SystemExit("Invalid service credential file")
    os.environ[name] = value


load("LITELLM_MASTER_KEY", "gateway-key")
load("REFERENCE_IDENTITY_JWT_SECRET", "identity-jwt-secret")
load("REFERENCE_AUDIT_SALT", "audit-salt")
if sys.argv[1] == "litellm":
    load("OPENROUTER_API_KEY", "openrouter-key")
    # Fixed executable/arguments from the pinned official image; no user command.
    os.execvp("litellm", ["litellm", "--config", "/reference/litellm.yaml", "--port", "4000"])  # noqa: S606, S607
elif sys.argv[1] == "open-webui":
    Path(os.environ["STATIC_DIR"]).mkdir(parents=True, exist_ok=True)
    load("WEBUI_SECRET_KEY", "webui-secret")
    load("WEBUI_ADMIN_PASSWORD", "admin-password")
    load("REFERENCE_POSTGRES_PASSWORD", "postgres-password")
    os.environ["PGVECTOR_DB_URL"] = (
        "postgresql://reference:"
        + os.environ.pop("REFERENCE_POSTGRES_PASSWORD")
        + "@webui-postgres:5432/reference"
    )
    os.environ["FORWARD_USER_INFO_HEADER_JWT_SECRET"] = os.environ["REFERENCE_IDENTITY_JWT_SECRET"]
    for name in ("OPENAI_API_KEY", "OPENAI_API_KEYS", "RAG_OPENAI_API_KEY", "RAG_EXTERNAL_RERANKER_API_KEY"):
        os.environ[name] = os.environ["LITELLM_MASTER_KEY"]
    os.execv("/bin/bash", ["/bin/bash", "start.sh"])  # noqa: S606
else:
    raise SystemExit("Unknown service")
