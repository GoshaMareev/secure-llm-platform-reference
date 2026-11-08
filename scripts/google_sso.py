"""Prepare private Google demo configuration; never infer document roles from email."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / ".local" / "google-sso"
CALLBACK = "http://localhost:4180/oauth2/callback"
ROLES = {"engineer": ["all", "engineers"], "reader": ["all"]}


def initialize(client_json: Path, directory: Path, emails: list[str]) -> None:
    # Validate everything before creating files. Never print provider input/errors.
    payload = json.loads(client_json.read_text(encoding="utf-8"))
    web = payload.get("web", {})
    client_id = web.get("client_id", "")
    client_secret = web.get("client_secret", "")
    if (
        not isinstance(client_id, str)
        or not re.fullmatch(r"[A-Za-z0-9.-]+\.apps\.googleusercontent\.com", client_id)
        or not isinstance(client_secret, str)
        or not client_secret
        or any(character.isspace() for character in client_secret)
        or CALLBACK not in web.get("redirect_uris", [])
    ):
        raise ValueError("Expected a Google Web client with the documented localhost callback")
    allowed = sorted({email.strip().casefold() for email in emails})
    if not allowed or any(not re.fullmatch(r"[^\s@*,]+@[^\s@*,]+\.[^\s@*,]+", e) for e in allowed):
        raise ValueError("At least one explicit email is required; wildcards are forbidden")
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        raise ValueError("Run as a non-root operator")
    directory = directory.absolute()
    if any(c in str(directory) for c in "\n\r'$\""):
        raise ValueError("Unsupported configuration directory characters")
    # Refuse reinitialization: it must not silently rotate cookies or reset grants.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    directory.chmod(0o700)
    values = {
        "client-secret": client_secret.encode(),
        "cookie-secret": secrets.token_bytes(32),
        "allowed-emails": ("\n".join(allowed) + "\n").encode(),
        "identity-policy.json": b'{"schema_version": 1, "subjects": {}}\n',
        "compose.env": (
            f"GOOGLE_OAUTH_CLIENT_ID={client_id}\n"
            f"GOOGLE_SSO_DIR='{directory}'\nGOOGLE_SSO_UID={uid}\nGOOGLE_SSO_GID={gid}\n"
            f"AUDIT_PSEUDONYM_SALT={secrets.token_hex(32)}\n"
        ).encode(),
    }
    for name, value in values.items():
        path = directory / name
        with path.open("xb") as handle:
            path.chmod(0o600)
            handle.write(value)
    # The API runs as UID 10001. Its read-only file mount has no parent directory;
    # the private host directory still prevents other host users reading the file.
    (directory / "identity-policy.json").chmod(0o644)


def grant(directory: Path, subject: str, role: str) -> None:
    if not re.fullmatch(r"[0-9]{1,128}", subject):
        raise ValueError("Use the numeric user field from the authenticated /oauth2/userinfo response")
    path = directory / "identity-policy.json"
    if path.is_symlink():
        raise ValueError("Policy must be an operator-owned regular file")
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1 or not isinstance(policy.get("subjects"), dict):
        raise ValueError("Invalid existing identity policy")
    policy["subjects"][subject] = ROLES[role]
    # Keep the inode: Compose uses a read-only bind mount of this file.
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--client-json", type=Path, required=True)
    init.add_argument("--allow-email", action="append", required=True)
    init.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    enroll = commands.add_parser("grant")
    enroll.add_argument("--subject", required=True)
    enroll.add_argument("--role", choices=ROLES, required=True)
    enroll.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.client_json, args.directory, args.allow_email)
            print(
                "Private Google configuration created. Access remains denied until explicit document grants."
            )
        else:
            grant(args.directory, args.subject, args.role)
            print("Document role saved. Restart rag-assistant to reload the policy.")
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        # Provider files may contain secrets. Do not echo exception values.
        parser.exit(1, "Configuration failed: check the input, callback, permissions and directory.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
