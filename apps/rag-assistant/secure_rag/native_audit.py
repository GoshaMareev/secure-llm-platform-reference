"""Durable metadata-only native audit spool. Historical v1 files stay readable."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

SEGMENT_BYTES = 10 * 1024 * 1024
SPOOL_BYTES = 100 * 1024 * 1024
RETENTION_SECONDS = 7 * 86400
MAX_EVENT_BYTES = 65536
EVENT_FIELDS = {
    "timestamp",
    "request_id",
    "event",
    "outcome",
    "verdict",
    "actor_hash",
    "model_alias",
    "blocked_role",
    "media",
    "mode",
    "corpus_version",
    "manifest_sha256",
    "stage",
    "status",
    "reason",
    "policy_version",
    "policy_sha256",
    "would_block",
    "scores",
    "model",
    "resolved_model",
    "latency_ms",
    "cost_usd",
}
COMPONENTS = {"gateway", "webui"}


class AuditUnavailable(OSError):
    """Stable fail-closed signal. No filesystem paths or event data in responses."""


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_event(event):
    if set(event) - (EVENT_FIELDS | {"schema_version", "event_id", "component"}):
        raise ValueError("unsupported_audit_field")
    if event.get("schema_version") != 2 or event.get("component") not in COMPONENTS:
        raise ValueError("invalid_audit_contract")
    for key in ("event_id", "request_id"):
        uuid.UUID(event[key])
    # Generic metadata must never transport arbitrary client strings.
    for key in ("event", "outcome", "verdict", "stage", "status", "reason", "model_alias", "blocked_role"):
        value = event.get(key)
        if value is not None and (
            not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value)
        ):
            raise ValueError("invalid_audit_metadata")
    if "actor_hash" in event and not re.fullmatch(
        r"[a-f0-9]{24}|unknown|native-rag-service", event["actor_hash"]
    ):
        raise ValueError("invalid_actor_hash")
    media = event.get("media")
    if media is not None and (
        not isinstance(media, dict)
        or set(media) - {"policy_version", "kind", "asr_revision", "redacted_kinds"}
    ):
        raise ValueError("invalid_media_metadata")
    if media is not None:
        for value in media.values():
            values = value if isinstance(value, list) else [value]
            if any(
                v is not None and (not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", v))
                for v in values
            ):
                raise ValueError("invalid_media_metadata")
    scores = event.get("scores", {})
    if not isinstance(scores, dict) or any(
        not re.fullmatch(r"(?:input_[a-z_]+|output_[a-z_]+|passage_[0-5]_[a-z_]+|untrusted_[0-3]_attack)", k)
        or isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not 0 <= v <= 1
        for k, v in scores.items()
    ):
        raise ValueError("invalid_decision_scores")
    for key in (
        "model",
        "resolved_model",
        "policy_version",
        "corpus_version",
        "manifest_sha256",
        "policy_sha256",
    ):
        if (
            key in event
            and event[key] is not None
            and (not isinstance(event[key], str) or not re.fullmatch(r"[A-Za-z0-9_./:-]{1,100}", event[key]))
        ):
            raise ValueError("invalid_audit_metadata")
    for key in ("timestamp", "latency_ms", "cost_usd"):
        value = event.get(key)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("invalid_audit_measurement")
    if event.get("would_block") not in {True, False, None}:
        raise ValueError("invalid_audit_verdict")
    raw = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError("audit_event_size_limit")
    return raw


def append_event(
    root: Path,
    component: str,
    record: dict,
    *,
    segment_bytes=SEGMENT_BYTES,
    spool_bytes=SPOOL_BYTES,
    checkpoint: Path | None = None,
):
    event = {**record, "schema_version": 2, "component": component, "event_id": str(uuid.uuid4())}
    raw = validate_event(event) + b"\n"
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".spool.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if checkpoint and checkpoint.exists():
            try:
                delivery = json.loads(checkpoint.read_text()).get("segments", {})
            except (OSError, ValueError):
                delivery = {}
            for path in root.glob("*.sealed.jsonl"):
                state = delivery.get(path.name, {})
                if (
                    state.get("offset", -1) >= path.stat().st_size
                    and time.time() - state.get("acked_at", time.time()) >= RETENTION_SECONDS
                ):
                    path.unlink()
                    fsync_directory(root)
        path = root / f"{component}.audit.jsonl"
        if path.exists() and path.stat().st_size + len(raw) > segment_bytes:
            path.replace(root / f"{component}.{time.time_ns()}.{uuid.uuid4().hex}.sealed.jsonl")
            fsync_directory(root)
        if sum(p.stat().st_size for p in root.glob("*.jsonl")) + len(raw) > spool_bytes:
            raise AuditUnavailable("audit_spool_full")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        original_size = os.lseek(fd, 0, os.SEEK_END)
        try:
            # Short writes and ENOSPC never acknowledge successful durable audit.
            view = memoryview(raw)
            while view:
                count = os.write(fd, view)
                if not count:
                    raise AuditUnavailable("audit_write_failed")
                view = view[count:]
            os.fsync(fd)
        except OSError:
            os.ftruncate(fd, original_size)
            os.fsync(fd)
            raise
        finally:
            os.close(fd)
        fsync_directory(root)
    return event["event_id"]


def emit(component, channel, record):
    root = Path(f"/var/log/reference/{channel}")
    if channel == "audit":
        return append_event(
            root, component, record, checkpoint=Path("/var/lib/audit-delivery/checkpoint.json")
        )
    # Operational logging is independent: errors must not replace request outcome.
    try:
        path = root / f"{component}.runtime.jsonl"
        root.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (json.dumps(record, allow_nan=False) + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        from .telemetry import LOG_ERRORS

        LOG_ERRORS.labels(component=component).inc()
