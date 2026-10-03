from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import IndexedChunk

SCHEMA_VERSION = 1


def write_index(path: Path, chunks: list[IndexedChunk], *, source_label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_label": source_label,
        "synthetic": True,
        "chunks": [chunk.to_dict() for chunk in chunks],
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_index(path: Path) -> tuple[dict[str, Any], list[IndexedChunk]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported index schema in {path}")
    if payload.get("synthetic") is not True:
        raise ValueError("Reference app accepts only indexes explicitly marked as synthetic")
    chunks = [IndexedChunk.from_dict(item) for item in payload.get("chunks", [])]
    return payload, chunks
