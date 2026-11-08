"""Content-addressed, immutable release manifests for the synthetic text corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

VERSION = re.compile(r"[1-9][0-9]*\.[0-9]+\.[0-9]+")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def contained_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if root not in candidate.parents or Path(relative).is_absolute():
        raise ValueError(f"Corpus path escapes source directory: {relative}")
    if not candidate.is_file():
        raise ValueError(f"Corpus file not found: {relative}")
    return candidate


def capture(source: Path) -> dict[str, Any]:
    root = source.resolve()
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    if catalog.get("synthetic") is not True:
        raise ValueError("Catalog must be explicitly marked as synthetic")
    version = catalog.get("corpus_version", "")
    corpus_id = catalog.get("corpus_id", "")
    if not VERSION.fullmatch(version) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", corpus_id):
        raise ValueError("Catalog requires corpus_id and a numeric corpus_version (e.g. 1.0.0)")
    documents = []
    ids, paths, filenames = set(), set(), set()
    for document in catalog["documents"]:
        if document["id"] in ids or document["path"] in paths:
            raise ValueError("Duplicate corpus document ID or path")
        filename = Path(document["path"]).name
        if filename in filenames:
            raise ValueError("Duplicate corpus filename is ambiguous in native Knowledge")
        if document.get("metadata", {}).get("audience") not in {"all", "engineers"}:
            raise ValueError("Corpus document requires a supported audience")
        filenames.add(filename)
        ids.add(document["id"])
        paths.add(document["path"])
        file = contained_file(root, document["path"])
        if file.suffix not in {".md", ".txt"} or file.stat().st_size > 1_000_000:
            raise ValueError("Unsupported corpus document type or size")
        documents.append({**document, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    if not documents:
        raise ValueError("Empty corpus")
    auxiliary = {
        name: hashlib.sha256(contained_file(root, name).read_bytes()).hexdigest()
        for name in ("glossary.json", "identity-policy.json")
    }
    payload = {
        "schema_version": 1,
        "synthetic": True,
        "corpus_id": corpus_id,
        "corpus_version": version,
        "catalog_sha256": fingerprint(catalog),
        "documents": sorted(documents, key=lambda item: item["id"]),
        "auxiliary_sha256": auxiliary,
    }
    return {**payload, "manifest_sha256": fingerprint(payload)}


def verify_manifest(manifest: dict[str, Any]) -> None:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("schema_version") != 1 or manifest.get("synthetic") is not True:
        raise ValueError("Unsupported corpus manifest")
    if manifest.get("manifest_sha256") != fingerprint(payload):
        raise ValueError("Corpus manifest digest mismatch")


def release(source: Path) -> dict[str, Any]:
    current = capture(source)
    path = source / "releases" / f"{current['corpus_version']}.json"
    expected = json.loads(path.read_text(encoding="utf-8"))
    verify_manifest(expected)
    if current != expected:
        raise ValueError("Corpus differs from its frozen release; restore inputs or publish a new version")
    return expected


def publish(source: Path) -> Path:
    manifest = capture(source)
    path = source / "releases" / f"{manifest['corpus_version']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a release, even when the new bytes happen to match.
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--publish", action="store_true", help="create a new immutable version manifest")
    args = parser.parse_args()
    if args.publish:
        print(f"Published {publish(args.source)}")
    else:
        manifest = release(args.source)
        print(f"Verified {manifest['corpus_id']}@{manifest['corpus_version']} {manifest['manifest_sha256']}")


if __name__ == "__main__":
    main()
