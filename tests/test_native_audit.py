"""Durability, bounded storage, replay and checkpoint/rotation safety."""

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/rag-assistant"), str(ROOT / "audit/delivery")]
import collector  # noqa: E402
from secure_rag.native_audit import AuditUnavailable, append_event, validate_event  # noqa: E402
from shipper import Shipper  # noqa: E402


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.event = {
            "timestamp": 1,
            "request_id": str(uuid.uuid4()),
            "event": "model_access",
            "verdict": "model_response_checked",
            "outcome": "allowed",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_rotation_retains_unacknowledged_segments_and_full_spool_fails(self):
        for _ in range(4):
            append_event(self.root, "gateway", self.event, segment_bytes=400, spool_bytes=2000)
        self.assertGreater(len(list(self.root.glob("*.sealed.jsonl"))), 0)
        with self.assertRaises(AuditUnavailable):
            append_event(self.root, "gateway", self.event, spool_bytes=500)
        events = [json.loads(line) for p in self.root.glob("*.jsonl") for line in p.read_text().splitlines()]
        self.assertEqual(len(events), 4)
        self.assertEqual(len({e["event_id"] for e in events}), 4)

    def test_fsync_failure_cannot_acknowledge_success(self):
        with patch("secure_rag.native_audit.os.fsync", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                append_event(self.root, "gateway", self.event)

    def test_raw_text_and_nested_media_text_are_rejected(self):
        event = {**self.event, "schema_version": 2, "event_id": str(uuid.uuid4()), "component": "gateway"}
        for extra in [
            {"prompt": "secret"},
            {"media": {"text": "secret"}},
            {"actor_hash": "synthetic@example.test"},
        ]:
            with self.assertRaises(ValueError):
                validate_event({**event, **extra})

    def test_durable_collector_replays_and_collisions(self):
        append_event(self.root, "gateway", self.event)
        event = json.loads((self.root / "gateway.audit.jsonl").read_text())
        with patch.object(collector, "DATABASE", self.root / "events.sqlite3"):
            collector.store(event)
            collector.store(dict(reversed(list(event.items()))))
            with collector.sqlite3.connect(collector.DATABASE) as db:
                self.assertEqual(db.execute("select count(*) from events").fetchone()[0], 1)
            with self.assertRaises(ValueError):
                collector.store({**event, "verdict": "different"})

    def test_cloudru_aggregate_event_is_durable_and_rejects_raw_payloads(self):
        observation = {
            **self.event, "event": "cloudru_pii_shadow", "mode": "shadow",
            "stage": "input_context", "scope": "after_presidio", "status": "checked",
            "text_count": 2, "changed_text_count": 1, "match_count": 1, "data_types": [3, 5],
        }
        append_event(self.root, "gateway", observation)
        stored = json.loads((self.root / "gateway.audit.jsonl").read_text())
        with patch.object(collector, "DATABASE", self.root / "scan-events.sqlite3"):
            collector.store(stored)
        for extra in (
            {"text_count": "synthetic@example.test"}, {"data_types": ["original"]},
            {"data_types": [True]}, {"match_count": -1}, {"scope": "raw text"},
            {"changed_text_count": 3}, {"placeholders": [{"original": "secret"}]},
        ):
            with self.assertRaises(ValueError):
                validate_event({**stored, **extra})

    def shipper(self, delivered):
        shipper = object.__new__(Shipper)
        shipper.spool = self.root
        shipper.checkpoint = self.root / "state/checkpoint.json"
        shipper.state = (
            json.loads(shipper.checkpoint.read_text()) if shipper.checkpoint.exists() else {"segments": {}}
        )
        shipper.deliver = lambda e: delivered.append(e["event_id"])
        return shipper

    def test_restart_and_rotation_do_not_skip_new_active_segment(self):
        append_event(self.root, "gateway", self.event)
        delivered = []
        first = self.shipper(delivered)
        first.once()
        append_event(self.root, "gateway", self.event, segment_bytes=400)
        restarted = self.shipper(delivered)
        restarted.once()
        self.assertEqual(len(set(delivered)), 2)
        self.assertEqual(len(delivered), 3)  # replay of renamed segment is deduplicated by collector

    def test_lost_ack_replays_after_restart(self):
        append_event(self.root, "gateway", self.event)
        ids = []
        shipper = self.shipper(ids)

        def lost(event):
            ids.append(event["event_id"])
            raise OSError("lost acknowledgement")

        shipper.deliver = lost
        with self.assertRaises(OSError):
            shipper.once()
        self.shipper(ids).once()
        self.assertEqual(ids[0], ids[1])
