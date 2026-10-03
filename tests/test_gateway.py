from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "rag-assistant"))

from secure_rag.gateway import OpenAICompatibleGateway  # noqa: E402


class GatewayTests(unittest.TestCase):
    def test_embedded_credentials_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exclude embedded credentials"):
            OpenAICompatibleGateway("https://user:password@example.invalid/v1", "model", "")

    def test_non_http_scheme_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be HTTP"):
            OpenAICompatibleGateway("file:///tmp/model", "model", "")

    def test_remote_http_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be HTTP"):
            OpenAICompatibleGateway("http://model.example.invalid/v1", "model", "")

    def test_loopback_http_is_allowed_for_local_demo(self) -> None:
        OpenAICompatibleGateway("http://127.0.0.1:4000/v1", "model", "")


if __name__ == "__main__":
    unittest.main()
