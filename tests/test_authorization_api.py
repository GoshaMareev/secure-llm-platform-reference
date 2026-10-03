from __future__ import annotations

import http.client
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "rag-assistant")]

from secure_rag.api import build_app  # noqa: E402
from secure_rag.authorization import IdentityPolicy, RetrievalScope  # noqa: E402
from secure_rag.retrieval import Retriever  # noqa: E402

from ingestion.corpus import fingerprint  # noqa: E402
from scripts.demo_runtime import ask, demo_settings, running_api  # noqa: E402

QUESTION = {"question": "Who can approve emergency production access?"}


class AuthorizationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.settings = demo_settings(Path(cls.temporary.name))
        cls.runtime = running_api(cls.settings)
        cls.base = cls.runtime.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.runtime.__exit__(None, None, None)
        cls.temporary.cleanup()

    def test_same_question_has_different_access_and_correlated_events(self):
        status, engineer = ask(self.base, QUESTION)
        self.assertEqual(status, 200)
        self.assertFalse(engineer["refused"])
        self.assertIn("incident commander", engineer["answer"])
        _, reader = ask(self.base, QUESTION, "reader-demo")
        self.assertTrue(reader["refused"])
        self.assertEqual(reader["citations"], [])
        for answer in (engineer, reader):
            ops = [json.loads(line) for line in self.settings.runtime_log_path.read_text().splitlines()]
            audit = [json.loads(line) for line in self.settings.audit_log_path.read_text().splitlines()]
            op = next(e for e in ops if e["request_id"] == answer["request_id"])
            au = next(e for e in audit if e["request_id"] == answer["request_id"])
            self.assertNotIn("prompt", op)
            self.assertNotIn("answer", op)
            self.assertNotIn("prompt", au)
            self.assertEqual(op["refused"], au["refused"])
            self.assertEqual(answer["corpus_version"], "1.1.0")
            self.assertEqual(
                au["corpus"], {key: answer[key] for key in ("corpus_id", "corpus_version", "manifest_sha256")}
            )

    def test_api_cannot_start_with_a_different_release_index(self):
        payload = json.loads(self.settings.index_path.read_text())
        payload["corpus"]["corpus_version"] = "2.0.0"
        payload["corpus"]["manifest_sha256"] = fingerprint(
            {k: v for k, v in payload["corpus"].items() if k != "manifest_sha256"}
        )
        index = Path(self.temporary.name) / "stale.json"
        index.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "different corpus"):
            build_app(replace(self.settings, index_path=index))

    def test_filter_and_body_identity_cannot_escalate_reader(self):
        status, answer = ask(
            self.base,
            {
                **QUESTION,
                "filters": {"audience": "engineers"},
                "actor_id": "engineer-demo",
            },
            "reader-demo",
        )
        self.assertEqual(status, 200)
        self.assertTrue(answer["blocked"])
        self.assertEqual(answer["citations"], [])
        self.assertEqual(answer["policy_verdicts"], ["scope_access_denied"])

    def test_reader_can_query_public_policy(self):
        status, answer = ask(
            self.base,
            {
                "question": "Can an end user choose an arbitrary provider URL?",
            },
            "reader-demo",
        )
        self.assertEqual(status, 200)
        self.assertFalse(answer["refused"])
        self.assertTrue(all(c["source_id"] == "model-usage" for c in answer["citations"]))

    def test_unknown_and_absent_identity_are_denied(self):
        self.assertEqual(ask(self.base, QUESTION, "unknown-demo")[0], 403)
        self.assertEqual(ask(self.base, {**QUESTION, "actor_id": "engineer-demo"}, None)[0], 401)

    def test_chunked_body_limit_is_enforced_without_content_length(self):
        parsed = urlparse(self.base)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        try:
            connection.request(
                "POST",
                "/v1/ask",
                body=iter([b"x" * 33_000, b"x" * 33_000]),
                headers={"content-type": "application/json"},
                encode_chunked=True,
            )
            self.assertEqual(connection.getresponse().status, 413)
        finally:
            connection.close()

    def test_scope_is_applied_before_ranking_and_missing_classification_is_denied(self):
        retriever = Retriever(self.settings.index_path)
        results = retriever.search("production access", scope=RetrievalScope())
        self.assertTrue(all(r.chunk.metadata["audience"] == "all" for r in results))
        self.assertFalse(RetrievalScope().allows({}))
        self.assertFalse(RetrievalScope().allows({"audience": "unclassified"}))

    def test_local_mode_ignores_both_forwarded_and_body_identity(self):
        settings = replace(self.settings, require_auth_header=False, local_actor_id="reader-demo")
        with running_api(settings) as base:
            _, answer = ask(base, {**QUESTION, "actor_id": "engineer-demo"}, "engineer-demo")
        self.assertTrue(answer["refused"])
        self.assertEqual(answer["citations"], [])

    def test_policy_unknown_subject_fails_closed(self):
        policy = IdentityPolicy(Path("sample-data/identity-policy.json"))
        with self.assertRaises(PermissionError):
            policy.scope_for("unknown-demo")
