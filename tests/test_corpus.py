"""Release integrity and stale-index regression tests."""

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/rag-assistant")]

from ingestion.build_index import build  # noqa: E402
from ingestion.corpus import capture, publish, release  # noqa: E402
from ingestion.store import read_index, write_index  # noqa: E402

# requests is supplied by the native image, not the offline runtime. This test
# exercises content/inventory validation with a fake operator and no HTTP calls.
with patch.dict(sys.modules, {"requests": SimpleNamespace()}):
    from scripts.bootstrap_openwebui import verify_corpus


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.source = Path(self.temporary.name) / "sample-data"
        shutil.copytree(ROOT / "sample-data", self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def test_release_is_reproducible_and_cannot_be_overwritten(self):
        self.assertEqual(capture(self.source), release(self.source))
        with self.assertRaises(FileExistsError):
            publish(self.source)

    def test_changed_document_cannot_reuse_version(self):
        file = self.source / "documents/access-control.md"
        file.write_text(file.read_text() + "\nChanged fact.\n")
        with self.assertRaisesRegex(ValueError, "frozen release"):
            release(self.source)

    def test_changed_scope_and_glossary_invalidate_version(self):
        for name in ("catalog.json", "glossary.json", "identity-policy.json"):
            file = self.source / name
            original = file.read_text()
            data = json.loads(original)
            if name == "catalog.json":
                data["documents"][0]["metadata"]["audience"] = "all"
            else:
                data["changed"] = []
            file.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "frozen release"):
                release(self.source)
            file.write_text(original)

    def test_new_version_preserves_previous_manifest(self):
        file = self.source / "catalog.json"
        catalog = json.loads(file.read_text())
        catalog["corpus_version"] = "1.2.0"
        file.write_text(json.dumps(catalog))
        previous = (self.source / "releases/1.0.0.json").read_bytes()
        publish(self.source)
        self.assertEqual(release(self.source)["corpus_version"], "1.2.0")
        self.assertEqual((self.source / "releases/1.0.0.json").read_bytes(), previous)

    def test_duplicate_document_and_path_escape_rejected(self):
        file = self.source / "catalog.json"
        original = json.loads(file.read_text())
        original["documents"].append(original["documents"][0])
        file.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            capture(self.source)
        original["documents"][0]["path"] = "../outside.md"
        file.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "escapes source"):
            capture(self.source)

    def test_ambiguous_filename_and_unmapped_audience_rejected(self):
        file = self.source / "catalog.json"
        original = json.loads(file.read_text())
        original["documents"][0]["metadata"]["audience"] = "unmapped"
        file.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "supported audience"):
            capture(self.source)
        original["documents"][0]["metadata"]["audience"] = "engineers"
        duplicate = {**original["documents"][0], "id": "another", "path": "other/access-control.md"}
        original["documents"].append(duplicate)
        file.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "filename"):
            capture(self.source)

    def test_tampered_index_and_manifest_rejected(self):
        index = Path(self.temporary.name) / "index.json"
        write_index(index, build(self.source), source_label="sample-data", corpus=release(self.source))
        payload, _ = read_index(index)
        payload["chunks"][0]["text"] = "Tampered"
        index.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "chunk digest"):
            read_index(index)
        payload["corpus"]["corpus_version"] = "2.0.0"
        index.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "manifest digest"):
            read_index(index)

    def test_legacy_unversioned_index_requires_rebuild(self):
        index = Path(self.temporary.name) / "legacy.json"
        index.write_text(json.dumps({"schema_version": 1, "synthetic": True, "chunks": []}))
        with self.assertRaisesRegex(ValueError, "Unsupported index schema"):
            read_index(index)


class NativeCorpusTests(unittest.TestCase):
    def setup_native(self, stored_bytes, extra=False):
        corpus = {
            "documents": [
                {
                    "id": "a",
                    "metadata": {"audience": "all"},
                    "sha256": hashlib.sha256(b"expected").hexdigest(),
                }
            ]
        }
        manifest = {
            "corpus": corpus,
            "knowledge": {"General": "general", "Engineering": "engineering"},
            "files": {"a": {"file_id": "file-a"}},
        }

        def call(method, path):
            items = [{"id": "file-a", "filename": "a.md"}] if "/general/" in path else []
            if extra:
                items.append({"id": "unversioned"})
            return {"items": items}

        operator = SimpleNamespace(
            call=call,
            session=SimpleNamespace(
                get=lambda *a, **kw: SimpleNamespace(status_code=200, content=stored_bytes)
            ),
        )
        return operator, manifest, corpus

    def test_same_filename_cannot_hide_changed_stored_content(self):
        verify_corpus(*self.setup_native(b"expected"))
        with self.assertRaisesRegex(ValueError, "stored content differs"):
            verify_corpus(*self.setup_native(b"modified"))

    def test_extra_native_file_is_not_part_of_frozen_release(self):
        with self.assertRaisesRegex(ValueError, "file inventory differs"):
            verify_corpus(*self.setup_native(b"expected", extra=True))
