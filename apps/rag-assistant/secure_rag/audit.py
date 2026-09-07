from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()


def _append_json(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        with _WRITE_LOCK:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    timestamp: str
    request_id: str
    route: str
    status_code: int
    latency_ms: float
    retrieved_chunks: int
    refused: bool


class OperationalLogger:
    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, event: OperationalEvent) -> None:
        _append_json(self._path, asdict(event))


class AuditWriter:
    def __init__(self, path: Path, *, pseudonym_salt: str, include_prompt: bool = False) -> None:
        self._path = path
        self._salt = pseudonym_salt.encode()
        self._include_prompt = include_prompt

    def write(
        self,
        *,
        request_id: str,
        actor_id: str,
        question: str,
        confidence: float,
        source_ids: list[str],
        refused: bool,
    ) -> None:
        event: dict[str, Any] = {
            "schema_version": 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "request_id": request_id,
            "actor_pseudonym": hashlib.sha256(self._salt + actor_id.encode()).hexdigest(),
            "prompt_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "prompt_characters": len(question),
            "confidence": round(confidence, 4),
            "source_ids": source_ids,
            "refused": refused,
        }
        if self._include_prompt:
            event["prompt"] = question
        _append_json(self._path, event)
