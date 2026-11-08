"""Private CPU-only OCR/STT. No provider keys, outbound network, or content logs."""

import asyncio
import base64
import csv
import hashlib
import io
import json
import math
import os
import subprocess
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import av
import numpy as np
from fastapi import FastAPI, Request
from faster_whisper import WhisperModel
from PIL import Image, ImageOps, UnidentifiedImageError
from secure_rag.media_guardrails import (
    ASR_REVISION,
    MAX_EXTRACTED_CHARACTERS,
    MediaRejected,
    decode_base64,
)

MAX_PIXELS = 4_000_000
MAX_AUDIO_SECONDS = 30
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
LOCK = threading.Lock()
MODEL = None


@asynccontextmanager
async def lifespan(app):
    global MODEL
    root = Path("/models/whisper-small")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["revision"] != ASR_REVISION:
        raise RuntimeError("Unexpected ASR revision")
    for name, expected in manifest["files"].items():
        digest = hashlib.sha256()
        with (root / name).open("rb") as file:
            for chunk in iter(lambda: file.read(1_048_576), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("ASR artifact integrity failure")
    MODEL = WhisperModel(
        str(root), device="cpu", compute_type="int8", cpu_threads=2, num_workers=1, local_files_only=True
    )
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
def health():
    return {"ready": MODEL is not None, "asr_revision": ASR_REVISION}


def image_text(raw, format_):
    try:
        with Image.open(io.BytesIO(raw)) as original:
            expected = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[format_]
            if original.format != expected or getattr(original, "n_frames", 1) != 1:
                raise MediaRejected("invalid_media")
            if original.width * original.height > MAX_PIXELS:
                raise MediaRejected("media_dimensions_limit")
            original.load()
            image = ImageOps.exif_transpose(original).convert("RGB")
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise MediaRejected("invalid_media") from None
    # A fresh image drops metadata even when a decoder copies info dictionaries.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    output = io.BytesIO()
    clean.save(output, format="PNG")
    with tempfile.TemporaryDirectory(prefix="ocr-") as directory:
        path = Path(directory, "pixels.png")
        path.write_bytes(output.getvalue())
        result = subprocess.run(  # noqa: S603 - fixed executable/arguments, private generated path
            ["/usr/bin/tesseract", str(path), "stdout", "-l", "eng+rus", "--psm", "11", "tsv"],
            capture_output=True,
            check=True,
            timeout=12,
        )
    words, confidences = [], []
    for row in csv.DictReader(io.StringIO(result.stdout.decode()), delimiter="\t"):
        text = row.get("text", "").strip()
        if not text:
            continue
        words.append(text)
        if any(c.isalnum() for c in text):
            confidences.append(float(row["conf"]) / 100)
    text = " ".join(words)
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise MediaRejected("media_dimensions_limit")
    if (
        any("\u0400" <= char <= "\u04ff" for char in text)
        and os.getenv("REFERENCE_RU_MEDIA_ENABLED", "false") != "true"
    ):
        raise MediaRejected("media_language_not_supported")
    confidence = min(confidences) if confidences else 1.0
    if confidence < 0.65:
        raise MediaRejected("media_low_confidence")
    return {
        "text": text,
        "confidence": confidence,
        "clean_data": base64.b64encode(output.getvalue()).decode(),
        "engine": "tesseract",
    }


def audio_text(raw, format_):
    if (format_ == "wav" and not (raw.startswith(b"RIFF") and raw[8:12] == b"WAVE")) or (
        format_ == "mp3" and not (raw.startswith(b"ID3") or raw[0] == 255)
    ):
        raise MediaRejected("invalid_media")
    chunks, samples = [], 0
    with av.open(io.BytesIO(raw)) as container:
        if len(container.streams.audio) != 1 or container.streams.video:
            raise MediaRejected("invalid_media")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            if frame.sample_rate > 48000 or len(frame.layout.channels) > 2:
                raise MediaRejected("invalid_media")
            for output in resampler.resample(frame):
                values = output.to_ndarray().reshape(-1)
                samples += len(values)
                if samples > MAX_AUDIO_SECONDS * 16000:
                    raise MediaRejected("media_duration_limit")
                chunks.append(values)
        for output in resampler.resample(None):
            values = output.to_ndarray().reshape(-1)
            samples += len(values)
            chunks.append(values)
    if samples > MAX_AUDIO_SECONDS * 16000:
        raise MediaRejected("media_duration_limit")
    if samples < 1600:
        raise MediaRejected("media_no_speech")
    waveform = np.concatenate(chunks).astype(np.float32)
    if not np.isfinite(waveform).all():
        raise MediaRejected("invalid_media")
    segments, info = MODEL.transcribe(
        waveform, beam_size=5, vad_filter=True, condition_on_previous_text=False, word_timestamps=False
    )
    if (
        info.language
        not in ({"en", "ru"} if os.getenv("REFERENCE_RU_MEDIA_ENABLED", "false") == "true" else {"en"})
        or not math.isfinite(info.language_probability)
        or info.language_probability < 0.70
    ):
        raise MediaRejected("media_language_not_supported")
    texts, confidence = [], 1.0
    for segment in segments:
        if (
            not math.isfinite(segment.no_speech_prob)
            or not math.isfinite(segment.avg_logprob)
            or segment.no_speech_prob > 0.60
        ):
            raise MediaRejected("media_low_confidence")
        confidence = min(confidence, math.exp(segment.avg_logprob))
        texts.append(segment.text.strip())
    text = " ".join(texts)
    if not text:
        raise MediaRejected("media_no_speech")
    if len(text) > MAX_EXTRACTED_CHARACTERS or confidence < 0.45:
        raise MediaRejected("media_low_confidence")
    return {
        "text": text,
        "confidence": confidence,
        "language": info.language,
        "revision": ASR_REVISION,
        "engine": "faster-whisper-small",
    }


def inspect(payload):
    kind = payload.get("kind")
    common = {"schema_version": 1, "kind": kind}
    if not LOCK.acquire(blocking=False):
        return {**common, "status": "unavailable", "reason": "media_capacity_exhausted"}
    try:
        format_ = payload.get("format")
        if (
            (kind == "image" and format_ not in {"png", "jpeg", "webp"})
            or (kind == "audio" and format_ not in {"wav", "mp3"})
            or kind not in {"image", "audio"}
        ):
            raise MediaRejected("invalid_media")
        raw = decode_base64(payload.get("data"))
        result = image_text(raw, format_) if kind == "image" else audio_text(raw, format_)
        return {**common, "status": "ok", **result}
    except MediaRejected as error:
        return {**common, "status": "blocked", "reason": str(error)}
    except Exception:
        # Native decoder/model failures must not print content-bearing errors.
        return {**common, "status": "unavailable", "reason": "media_check_unavailable"}
    finally:
        LOCK.release()


@app.post("/inspect")
async def inspect_media(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 5_400_000:
            return {"schema_version": 1, "kind": "unknown", "status": "blocked", "reason": "invalid_media"}
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")
    except ValueError:
        return {"schema_version": 1, "kind": "unknown", "status": "blocked", "reason": "invalid_media"}
    return await asyncio.to_thread(inspect, payload)
