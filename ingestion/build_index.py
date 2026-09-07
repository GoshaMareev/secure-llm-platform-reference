from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .chunking import chunk_text
from .models import IndexedChunk
from .store import write_index
from .vectorizer import tokenize, vectorize

MAX_DOCUMENT_BYTES = 1_000_000
ALLOWED_SUFFIXES = {".md", ".txt"}


def _contained_file(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Document path escapes source directory: {relative_path}")
    if candidate.suffix.casefold() not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported document type: {relative_path}")
    if not candidate.is_file():
        raise ValueError(f"Document not found: {relative_path}")
    if candidate.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError(f"Document exceeds {MAX_DOCUMENT_BYTES} bytes: {relative_path}")
    return candidate


def build(source: Path) -> list[IndexedChunk]:
    root = source.resolve()
    with (root / "catalog.json").open(encoding="utf-8") as handle:
        catalog: dict[str, Any] = json.load(handle)
    if catalog.get("synthetic") is not True:
        raise ValueError("Catalog must be explicitly marked as synthetic")

    chunks: list[IndexedChunk] = []
    for document in catalog.get("documents", []):
        document_id = str(document["id"])
        relative_path = str(document["path"])
        file_path = _contained_file(root, relative_path)
        text = file_path.read_text(encoding="utf-8")
        if file_path.suffix.casefold() == ".md":
            text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        metadata = {str(key): str(value) for key, value in dict(document.get("metadata", {})).items()}
        title = str(document["title"])
        for index, part in enumerate(chunk_text(text)):
            digest = hashlib.sha256(f"{document_id}:{index}:{part}".encode()).hexdigest()[:16]
            tokens = tokenize(f"{title} {part}")
            chunks.append(
                IndexedChunk(
                    id=f"chunk-{digest}",
                    document_id=document_id,
                    title=title,
                    text=part,
                    source_path=relative_path,
                    metadata=metadata,
                    tokens=tokens,
                    vector=vectorize(tokens),
                )
            )
    if not chunks:
        raise ValueError("Catalog produced an empty index")
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deterministic index from synthetic sample data.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    chunks = build(args.source)
    write_index(args.output, chunks, source_label=args.source.name)
    print(f"Indexed {len(chunks)} chunks into {args.output}")


if __name__ == "__main__":
    main()
