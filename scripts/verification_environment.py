"""Create isolated synthetic identities/credentials; no hosted provider key."""

import json
import os

from full_stack_secrets import ROOT, initialize


def create():
    directory = ROOT / ".local/verification"
    if not directory.exists():
        initialize(directory)
    users = {
        "users": [
            {"scope": "reader", "email": "verification-reader@example.test"},
            {"scope": "engineer", "email": "verification-engineer@example.test"},
        ]
    }
    (directory / "identities.json").write_text(json.dumps(users) + "\n")
    (directory / "provider-key").write_text("verification-not-secret")
    (directory / "fault.json").write_text('{"mode":"normal","operation":"all","delay_ms":100}\n')
    (directory / "fault.json").chmod(0o644)  # private parent directory, read-only container mount
    (directory / "compose.env").write_text(
        f"FULL_STACK_DIR='{directory}'\nFULL_STACK_UID={os.getuid()}\nFULL_STACK_GID={os.getgid()}\n"
        f"OPENROUTER_KEY_FILE='{directory / 'provider-key'}'\nGOOGLE_SSO_DIR='{directory}'\n"
        f"GOOGLE_SSO_UID={os.getuid()}\nGOOGLE_SSO_GID={os.getgid()}\nGOOGLE_OAUTH_CLIENT_ID=verification-synthetic\n"
    )
    print("Isolated verification environment ready; no hosted key.")


if __name__ == "__main__":
    create()
