"""Tiny synthetic media probes through LiteLLM; run in Open WebUI container.

Image/audio are generated in memory. Optional video must be a synthetic fixture,
not a personal recording. This exercises model input modalities, not STT/TTS or
Open WebUI's media-upload workflows. Requires authorization for hosted calls.
"""

import argparse
import base64
import io
import json
import math
import struct
import time
import uuid
import wave
import zlib
from pathlib import Path

import jwt
import requests


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = (b"\x00" + b"\xff\x00\x00" * 32) * 32
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setparams((1, 2, 16000, 16000, "NONE", "not compressed"))
        file.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(16000)
            )
        )
    return output.getvalue()


def verify(video):
    manifest = json.loads(Path("/app/backend/data/reference-manifest.json").read_text())
    subject = manifest["users"]["reader"]
    signing = Path("/run/secrets/identity-jwt-secret").read_text().strip()
    now = int(time.time())
    identity = jwt.encode(
        {"iss": "open-webui", "sub": subject, "role": "user", "iat": now, "exp": now + 300},
        signing,
        algorithm="HS256",
    )
    headers = {
        "Authorization": "Bearer " + Path("/run/secrets/gateway-key").read_text().strip(),
        "X-OpenWebUI-User-JWT": identity,
    }

    def b64(data):
        return base64.b64encode(data).decode()

    probes = [
        (
            "vision",
            "reference-vision",
            "What is the dominant color? Answer in one word.",
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64(png())}},
            ("red",),
        ),
        (
            "audio input",
            "reference-multimodal",
            "Describe the audible sound in at most 15 words.",
            {"type": "input_audio", "input_audio": {"data": b64(audio()), "format": "wav"}},
            ("tone", "beep", "steady", "sine"),
        ),
    ]
    if video:
        probes.append(
            (
                "video input",
                "reference-multimodal",
                "What color fills the video? Answer in one word.",
                {
                    "type": "video_url",
                    "video_url": {"url": "data:video/mp4;base64," + b64(video.read_bytes())},
                },
                ("red",),
            )
        )
    results = []
    for name, model, question, media, expected in probes:
        request_id = str(uuid.uuid4())
        context = jwt.encode(
            {
                "iss": "reference-rag-policy",
                "sub": subject,
                "request_id": request_id,
                "iat": now,
                "exp": now + 300,
            },
            signing,
            algorithm="HS256",
        )
        response = requests.post(
            "http://litellm:4000/v1/chat/completions",
            headers=headers,
            json={
                "model": model,
                "max_tokens": 128,
                "stream": False,
                "reference_context_token": context,
                "messages": [{"role": "user", "content": [{"type": "text", "text": question}, media]}],
            },
            timeout=90,
        )
        content = " ".join(
            c.get("message", {}).get("content") or "" for c in response.json().get("choices", [])
        )
        results.append(
            {
                "modality": name,
                "model_alias": model,
                "http_status": response.status_code,
                "passed": response.status_code == 200 and any(term in content.lower() for term in expected),
                "answer": content if response.status_code == 200 else "Provider error omitted",
                "request_id": request_id,
            }
        )
    print(json.dumps(results, indent=2))
    return all(result["passed"] for result in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if verify(args.video) else 1)
