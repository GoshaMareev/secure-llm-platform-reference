"""Rollback retains historical facts; a tampered active manifest cannot activate."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingestion.corpus import release  # noqa: E402
from ingestion.native_release import active_release, source_for  # noqa: E402


class NativeReleaseTests(unittest.TestCase):
    def test_round_trip_retains_documents_and_checks_active_digest(self):
        root = ROOT / "sample-data"
        old, new = release(source_for("1.0.0", root)), release(source_for("1.1.0", root))
        self.assertEqual(old["documents"], new["documents"])
        self.assertNotEqual(old["manifest_sha256"], new["manifest_sha256"])
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "active.json"
            for corpus in [old, new, old]:
                manifest.write_text(json.dumps({"corpus": corpus}))
                self.assertEqual(active_release(root, manifest), corpus)
            old["manifest_sha256"] = "tampered"
            manifest.write_text(json.dumps({"corpus": old}))
            with self.assertRaises(ValueError):
                active_release(root, manifest)
        with self.assertRaises(ValueError):
            source_for("../../unknown", root)
