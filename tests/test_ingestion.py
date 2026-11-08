from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.build_index import build  # noqa: E402
from ingestion.chunking import chunk_text  # noqa: E402


class IngestionTests(unittest.TestCase):
    def test_chunking_uses_overlap(self) -> None:
        chunks = chunk_text(" ".join(str(value) for value in range(20)), max_words=10, overlap_words=2)
        self.assertEqual(chunks[0].split()[-2:], chunks[1].split()[:2])

    def test_sample_catalog_builds_only_synthetic_content(self) -> None:
        chunks = build(ROOT / "sample-data")
        self.assertGreaterEqual(len(chunks), 3)
        self.assertEqual({chunk.metadata["system"] for chunk in chunks}, {"platform", "ai"})

    def test_catalog_path_cannot_escape_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "catalog.json").write_text(
                json.dumps(
                    {
                        "synthetic": True,
                        "documents": [
                            {"id": "escape", "path": "../outside.md", "title": "Escape", "metadata": {}}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "escapes source"):
                build(root)


if __name__ == "__main__":
    unittest.main()
