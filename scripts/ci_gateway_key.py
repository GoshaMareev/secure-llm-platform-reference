"""Register a runner mask before exporting the ephemeral test gateway key."""

import os
import secrets
from pathlib import Path


def main() -> None:
    environment = Path(os.environ["GITHUB_ENV"])
    key = "sk-" + secrets.token_hex(24)
    # GITHUB_ENV alone does not mask later steps' environment dumps.
    print(f"::add-mask::{key}", flush=True)
    with environment.open("a", encoding="utf-8") as handle:
        handle.write(f"LITELLM_MASTER_KEY={key}\n")


if __name__ == "__main__":
    main()
