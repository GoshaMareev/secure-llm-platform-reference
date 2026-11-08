from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "rag-assistant"))

from secure_rag.settings import Settings  # noqa: E402


class SettingsTests(unittest.TestCase):
    def test_paths_must_not_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, "logs")
            with patch.dict(
                os.environ,
                {
                    "RUNTIME_LOG_PATH": os.path.join(root, "runtime.jsonl"),
                    "AUDIT_LOG_PATH": os.path.join(root, "runtime", "audit.jsonl"),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "must be separate"):
                    Settings.from_env()

    def test_missing_salt_gets_ephemeral_secret(self) -> None:
        with patch.dict(os.environ, {"AUDIT_PSEUDONYM_SALT": ""}, clear=False):
            settings = Settings.from_env()
        self.assertGreaterEqual(len(settings.audit_pseudonym_salt), 32)


if __name__ == "__main__":
    unittest.main()
