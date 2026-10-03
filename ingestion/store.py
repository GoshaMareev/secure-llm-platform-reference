from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .corpus import fingerprint, verify_manifest
from .models import IndexedChunk

SCHEMA_VERSION = 2


def write_index(path: Path, chunks: list[IndexedChunk], *, source_label: str, corpus: dict[str, Any]) -> None:
    verify_manifest(corpus)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_label": source_label,
        "synthetic": True,
        "corpus": corpus,
        "pipeline_sha256": fingerprint(
            {p.name: p.read_text(encoding="utf-8") for p in sorted(Path(__file__).parent.glob("*.py"))}
        ),
        "chunks_sha256": fingerprint([chunk.to_dict() for chunk in chunks]),
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
    verify_manifest(payload["corpus"])
    if payload.get("chunks_sha256") != fingerprint(payload.get("chunks", [])):
        raise ValueError("Index chunk digest mismatch")
    chunks = [IndexedChunk.from_dict(item) for item in payload.get("chunks", [])]
    return payload, chunks
