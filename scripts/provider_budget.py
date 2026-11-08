"""Operator-only hosted-run budget preflight; never print credentials."""

import argparse
import json
import ssl
from pathlib import Path
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


TOTAL_LIMIT = 5.0
RUN_LIMIT = 1.0


def remaining(key_file):
    key = key_file.read_text().strip()
    request = Request("https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key})
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=10) as response:
        data = json.loads(response.read(65536))["data"]
    used = float(data["usage"])
    limit = min(TOTAL_LIMIT, float(data["limit"])) if data.get("limit") is not None else TOTAL_LIMIT
    return used, max(0.0, limit - used)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, default=Path(".local/openrouter/api-key"))
    parser.add_argument("--reserve", type=float, default=RUN_LIMIT)
    args = parser.parse_args()
    if not 0 < args.reserve <= RUN_LIMIT:
        raise SystemExit("A run must reserve at most $1")
    try:
        used, available = remaining(args.key_file)
    except Exception:
        raise SystemExit("Budget preflight unavailable; hosted calls blocked") from None
    print(json.dumps({"used_usd": used, "remaining_usd": available, "run_cap_usd": args.reserve}))
    raise SystemExit(0 if available >= args.reserve else 1)
