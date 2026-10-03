"""Create local service credentials. The OpenRouter key is imported separately."""

import argparse
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def initialize(directory: Path) -> None:
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    directory.chmod(0o700)
    values = {
        "gateway-key": "sk-reference-" + secrets.token_hex(32),
        "webui-secret": secrets.token_hex(32),
        "identity-jwt-secret": secrets.token_hex(32),
        "admin-password": secrets.token_urlsafe(36),
        "audit-salt": secrets.token_hex(32),
        "postgres-password": secrets.token_hex(32),
    }
    for name, value in values.items():
        path = directory / name
        path.touch(mode=0o600, exist_ok=False)
        path.write_text(value)
    # The database runs as its own UID; the parent host directory stays 0700.
    (directory / "postgres-password").chmod(0o644)
    path = directory / "identities.json"
    path.touch(mode=0o600, exist_ok=False)
    path.write_text(json.dumps({"users": []}, indent=2) + "\n")
    env = directory / "compose.env"
    env.touch(mode=0o600, exist_ok=False)
    env.write_text(
        f"FULL_STACK_DIR='{directory.absolute()}'\n"
        f"FULL_STACK_UID={os.getuid()}\nFULL_STACK_GID={os.getgid()}\n"
        f"OPENROUTER_KEY_FILE='{ROOT / '.local/openrouter/api-key'}'\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/full-stack")
    args = parser.parse_args()
    initialize(args.directory)
    print("Local credentials created. No provider key or document access was granted.")
