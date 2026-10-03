from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "rag-assistant")]

from scripts.demo_runtime import demo_settings, running_api  # noqa: E402


class DemoWorkspaceTests(unittest.TestCase):
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

    def get(self, path, actor=None, base=None):
        headers = {"x-forwarded-user": actor} if actor else {}
        request = Request((base or self.base) + path, headers=headers)  # noqa: S310 - loopback fixture
        try:
            response = urlopen(request, timeout=5)  # noqa: S310 - loopback fixture only
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_session_reports_only_the_authenticated_subjects_permissions(self):
        status, headers, raw = self.get("/v1/session", "engineer-demo")
        self.assertEqual(status, 200)
        engineer = json.loads(raw)
        self.assertEqual(engineer["role"], "engineer")
        self.assertEqual(engineer["audiences"], ["all", "engineers"])
        self.assertEqual(engineer["auth_mode"], "proxy")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn(b"engineer-demo", raw)
        self.assertNotIn("email", engineer)
        self.assertNotIn("subject", engineer)
        status, _, raw = self.get(
            "/v1/session?role=engineer&actor_id=engineer-demo&audience=engineers", "reader-demo"
        )
        self.assertEqual(status, 200)
        reader = json.loads(raw)
        self.assertEqual(reader["role"], "reader")
        self.assertEqual(reader["audiences"], ["all"])

    def test_missing_and_unknown_subject_cannot_obtain_session_policy(self):
        self.assertEqual(self.get("/v1/session")[0], 401)
        status, headers, raw = self.get("/v1/session", "unknown-demo")
        self.assertEqual(status, 403)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn(b"audiences", raw)
        self.assertNotIn(b"unknown-demo", raw)

    def test_local_session_ignores_spoofed_headers(self):
        settings = replace(self.settings, require_auth_header=False, local_actor_id="reader-demo")
        with running_api(settings) as base:
            status, _, raw = self.get("/v1/session", "engineer-demo", base)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertEqual(data["audiences"], ["all"])
        self.assertEqual(data["auth_mode"], "local")

    def test_workspace_and_assets_have_browser_security_headers(self):
        status, headers, raw = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Ask with evidence", raw)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        status, headers, _ = self.get("/demo-assets/workspace.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/demo-assets/../settings.py", "/demo-assets/%2e%2e/settings.py"):
            self.assertEqual(self.get(path)[0], 404)
