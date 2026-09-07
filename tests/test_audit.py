from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "rag-assistant"))

from secure_rag.audit import AuditWriter, OperationalEvent, OperationalLogger  # noqa: E402


class AuditTests(unittest.TestCase):
    def test_operational_event_cannot_contain_prompt(self) -> None:
        self.assertNotIn("prompt", OperationalEvent.__dataclass_fields__)
        self.assertNotIn("answer", OperationalEvent.__dataclass_fields__)

    def test_default_audit_event_hashes_identity_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            AuditWriter(path, pseudonym_salt="synthetic-test-salt").write(
                request_id="00000000-0000-4000-8000-000000000001",
                actor_id="fictional-user",
                question="Synthetic private question",
                confidence=0.5,
                source_ids=["access-control"],
                refused=False,
            )
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("prompt", event)
            self.assertNotIn("fictional-user", json.dumps(event))
            self.assertEqual(event["prompt_characters"], len("Synthetic private question"))

    def test_operational_log_contains_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.jsonl"
            OperationalLogger(path).write(
                OperationalEvent(
                    timestamp=datetime.now(UTC).isoformat(),
                    request_id="request-1",
                    route="/v1/ask",
                    status_code=200,
                    latency_ms=12.5,
                    retrieved_chunks=2,
                    refused=False,
                )
            )
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(event), set(OperationalEvent.__dataclass_fields__))


if __name__ == "__main__":
    unittest.main()
