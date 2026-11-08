"""Real local OCR/STT + Presidio + gateway callback; no hosted inference or keys.

Run in the pinned LiteLLM image on the private platform network, with /fixtures
containing locally synthesized PNG images and WAV speech fixtures.
"""

import argparse
import asyncio
import base64
import hashlib
import io
import json
import math
import os
import secrets
import struct
import time
import uuid
import wave
from pathlib import Path

import jwt
from fastapi import HTTPException
from reference_gateway import ReferencePolicy
from secure_rag.media_guardrails import ASR_REVISION, MEDIA_POLICY_VERSION


def image(name):
    return Path("/fixtures", name + ".png").read_bytes()


def tone():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 16000, 16000, "NONE", "not compressed"))
        audio.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * t / 16000))) for t in range(16000)
            )
        )
    return output.getvalue()


def image_part(raw):
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(raw).decode()},
    }


def audio_part(raw):
    return {"type": "input_audio", "input_audio": {"data": base64.b64encode(raw).decode(), "format": "wav"}}


async def verify(report_path):
    os.environ["REFERENCE_DECISION_MODE"] = "off"
    os.environ["REFERENCE_IDENTITY_JWT_SECRET"] = secrets.token_hex(32)
    os.environ["REFERENCE_AUDIT_SALT"] = "synthetic-media-audit-salt"
    policy = ReferencePolicy()
    events = []
    policy.record = lambda data, verdict, outcome, **details: events.append(
        {
            "verdict": verdict,
            "outcome": outcome,
            **details,
        }
    )
    fixtures = Path("/fixtures")
    cases = [
        ("image-policy", image_part(image("policy")), "image_text_checked"),
        ("image-no-text", image_part(image("empty")), "image_text_checked"),
        ("image-email", image_part(image("email")), "image_sensitive_text_blocked"),
        ("image-phone", image_part(image("phone")), "image_sensitive_text_blocked"),
        ("image-card", image_part(image("card")), "image_sensitive_text_blocked"),
        ("image-credential", image_part(image("credential")), "image_sensitive_text_blocked"),
        ("image-name", image_part(image("name")), "image_sensitive_text_blocked"),
        (
            "image-injection",
            image_part(image("injection")),
            "media_injection_blocked",
        ),
        ("image-metadata", image_part(image("metadata")), "image_text_checked"),
        ("image-corrupt", image_part(b"corrupt pixels"), "invalid_media"),
        ("image-dimensions", image_part(image("dimensions")), "media_dimensions_limit"),
        (
            "remote-url",
            {"type": "image_url", "image_url": {"url": "http://127.0.0.1/private"}},
            "remote_media_blocked",
        ),
        (
            "video",
            {"type": "video_url", "video_url": {"url": "https://example.test/video"}},
            "unsupported_media_input",
        ),
        ("audio-benign", audio_part((fixtures / "benign.wav").read_bytes()), "audio_transcript_checked"),
        (
            "audio-email",
            audio_part((fixtures / "email.wav").read_bytes()),
            {"audio_transcript_redacted", "audio_sensitive_text_unresolved"},
        ),
        ("audio-injection", audio_part((fixtures / "injection.wav").read_bytes()), "media_injection_blocked"),
        (
            "audio-tone",
            audio_part(tone()),
            {"media_no_speech", "media_low_confidence", "media_language_not_supported"},
        ),
        ("audio-corrupt", audio_part(b"corrupt recording"), "invalid_media"),
    ]
    results = []
    for case_id, part, expected in cases:
        events.clear()
        now = int(time.time())
        subject = "synthetic-media-reader"
        claims = {"iss": "open-webui", "sub": subject, "role": "user", "iat": now, "exp": now + 300}
        context = {**claims, "iss": "reference-rag-policy", "request_id": str(uuid.uuid4())}
        data = {
            "model": "reference-vision" if part["type"] == "image_url" else "reference-multimodal",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Read the attachment."}, part]}
            ],
            "secret_fields": {
                "raw_headers": {
                    "X-OpenWebUI-User-JWT": jwt.encode(
                        claims,
                        os.environ["REFERENCE_IDENTITY_JWT_SECRET"],
                        algorithm="HS256",
                    )
                }
            },
            "reference_context_token": jwt.encode(
                context, os.environ["REFERENCE_IDENTITY_JWT_SECRET"], algorithm="HS256"
            ),
        }
        started = time.monotonic()
        privacy_ok = True
        try:
            checked = await policy.async_pre_call_hook(None, None, data, "completion")
            verdict = events[-1]["verdict"]
            content = checked["messages"][0]["content"]
            if case_id.startswith("audio-"):
                privacy_ok = all(p["type"] == "text" for p in content)
                if case_id == "audio-email":
                    privacy_ok &= "synthetic" not in json.dumps(
                        content
                    ).lower() and "[REDACTED_EMAIL]" in str(content)
            if case_id == "image-metadata":
                pixels = base64.b64decode(content[-1]["image_url"]["url"].split(",", 1)[1])
                privacy_ok &= b"synthetic" not in pixels and b"tEXt" not in pixels
        except HTTPException as error:
            verdict = error.detail["verdict"]
            privacy_ok = "synthetic@" not in json.dumps(error.detail)
        expected_set = expected if isinstance(expected, set) else {expected}
        results.append(
            {
                "case_id": case_id,
                "verdict": verdict,
                "passed": verdict in expected_set and privacy_ok,
                "privacy_check": privacy_ok,
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            }
        )
    report = {
        "policy_version": MEDIA_POLICY_VERSION,
        "asr_revision": ASR_REVISION,
        "test_mode": "local-only: actual OCR/STT/Presidio and gateway pre-call hook, no provider request",
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "cases": results,
        "source_sha256": {
            name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for name, path in {
                "gateway": "/reference/reference_gateway.py",
                "media_policy": "/reference/secure-rag/secure_rag/media_guardrails.py",
                "verifier": __file__,
            }.items()
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report["passed"] == report["total"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(verify(args.report)) else 1)
