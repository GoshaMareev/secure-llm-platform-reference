"""Operator-selected native corpus; fixed source locations and fail-closed validation."""

import json
from pathlib import Path

from ingestion.corpus import release

ROOT = Path("/reference/sample-data")
MANIFEST = Path("/app/backend/data/reference-manifest.json")


def source_for(version, root=ROOT):
    if version == "1.1.0":
        return root
    if version == "1.0.0":
        return root / "snapshots/1.0.0"
    raise ValueError("Unsupported native corpus release")


def active_release(root=ROOT, manifest_path=MANIFEST):
    manifest = json.loads(manifest_path.read_text())
    corpus = release(source_for(manifest["corpus"]["corpus_version"], root))
    if corpus != manifest["corpus"]:
        raise ValueError("Active native corpus is unconfirmed")
    return corpus
