"""Synthetic media through a regular user's native WebUI chat API.

Run inside the private WebUI container with generated fixtures. --live permits
hosted calls with checked image pixels and sanitized speech transcripts.
The report contains only check labels, HTTP status and booleans.
"""

import argparse
import base64
import json
from pathlib import Path

import requests


def verify(fixtures, live, base):
    identities = json.loads(Path("/run/secrets/identity-enrollment").read_text())["users"]
    reader = next(identity for identity in identities if identity["scope"] == "reader")
    session = requests.Session()
    response = session.post(
        base + "/api/v1/auths/signin",
        headers={"X-Forwarded-Email": reader["email"]},
        json={"email": reader["email"], "password": "internal-trusted-header"},
        timeout=30,
    )
    response.raise_for_status()
    user = response.json()
    if user["role"] != "user":
        raise ValueError("Media verification requires a regular user")
    session.headers["Authorization"] = "Bearer " + user["token"]
    cases = [
        ("image-email", "reference-vision", "email.png", "image_sensitive_text_blocked"),
        ("image-injection", "reference-vision", "injection.png", "media_injection_blocked"),
        ("audio-email", "reference-multimodal", "email.wav", None),
        ("audio-injection", "reference-multimodal", "injection.wav", "media_injection_blocked"),
    ]
    if live:
        cases.extend(
            [
                ("image-policy", "reference-vision", "policy.png", "allowed"),
                ("audio-benign", "reference-multimodal", "benign.wav", "allowed"),
            ]
        )
    results = []
    audit_path = Path("/var/log/reference/audit/gateway.audit.jsonl")
    for label, alias, filename, expected in cases:
        audit_before = len(audit_path.read_text().splitlines())
        encoded = base64.b64encode((fixtures / filename).read_bytes()).decode()
        media = (
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + encoded}}
            if filename.endswith(".png")
            else {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}}
        )
        response = session.post(
            base + "/api/chat/completions",
            json={
                "model": alias,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Summarize the attachment in one sentence."},
                            media,
                        ],
                    }
                ],
            },
            timeout=150,
        )
        # WebUI intentionally returns a generic policy denial. Verify the
        # actual stable media verdict in the private metadata-only audit stream.
        events = [json.loads(line) for line in audit_path.read_text().splitlines()[audit_before:]]
        media_events = [
            event
            for event in events
            if event.get("event") == "model_access"
            and event.get("media")
            and event.get("model_alias") == alias
        ]
        event = media_events[0] if len(media_events) == 1 else {}
        verdict = event.get("verdict")
        # Cross-architecture ASR may recover the email or conservatively deny
        # it. Neither accepted raw address nor unscreened audio is an outcome.
        if label == "audio-email":
            passed = (response.status_code == 400 and verdict == "audio_sensitive_text_unresolved") or (
                live
                and response.status_code == 200
                and verdict == "audio_transcript_redacted"
                and "synthetic" not in response.text.lower()
            )
        elif expected == "allowed":
            passed = (
                response.status_code == 200
                and bool(response.json().get("choices"))
                and verdict
                == ("image_text_checked" if filename.endswith(".png") else "audio_transcript_checked")
            )
        else:
            passed = response.status_code == 400 and verdict == expected
        results.append(
            {
                "check": label,
                "http_status": response.status_code,
                "verdict": verdict,
                "request_id": event.get("request_id"),
                "passed": passed,
            }
        )
    return {
        "live": live,
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "checks": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--base-url",
        choices=("http://127.0.0.1:8080", "http://open-webui:8080"),
        default="http://127.0.0.1:8080",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required: accepted synthetic media incurs hosted model charges")
    try:
        report = verify(args.fixtures, args.live, args.base_url)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["passed"] == report["total"] else 1)
    except (requests.RequestException, OSError, KeyError, ValueError):
        print(json.dumps({"passed": False, "reason": "native_media_verification_unavailable"}))
        raise SystemExit(1) from None
