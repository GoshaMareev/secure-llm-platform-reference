from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "rag-assistant")]

from secure_rag.authorization import IdentityPolicy  # noqa: E402

from scripts.google_sso import CALLBACK, grant, initialize  # noqa: E402


class GoogleSsoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "private"
        self.client = Path(self.temporary.name) / "client.json"
        self.client.write_text(
            json.dumps(
                {
                    "web": {
                        "client_id": "0000-demo.apps.googleusercontent.com",
                        "client_secret": "synthetic-secret",
                        "redirect_uris": [CALLBACK],
                    }
                }
            )
        )

    def test_bootstrap_denies_every_subject_until_operator_grants(self):
        initialize(self.client, self.directory, ["reader@example.test", "engineer@example.test"])
        policy = IdentityPolicy(self.directory / "identity-policy.json")
        with self.assertRaises(PermissionError):
            policy.scope_for("123456")
        with self.assertRaises(PermissionError):
            policy.scope_for("engineer@example.test")
        grant(self.directory, "123456", "engineer")
        grant(self.directory, "654321", "reader")
        policy = IdentityPolicy(self.directory / "identity-policy.json")
        self.assertEqual(policy.scope_for("123456").audiences, frozenset({"all", "engineers"}))
        self.assertEqual(policy.scope_for("654321").audiences, frozenset({"all"}))
        with self.assertRaises(ValueError):
            grant(self.directory, "engineer@example.test", "engineer")

    def test_secrets_have_private_permissions_and_reinit_cannot_reset_roles(self):
        initialize(self.client, self.directory, ["engineer@example.test"])
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.directory / "cookie-secret").stat().st_mode & 0o777, 0o600)
        self.assertEqual(len((self.directory / "cookie-secret").read_bytes()), 32)
        env = (self.directory / "compose.env").read_text()
        self.assertNotIn("synthetic-secret", env)
        self.assertIn(f"GOOGLE_SSO_UID={os.getuid()}", env)
        grant(self.directory, "123456", "engineer")
        with self.assertRaises(FileExistsError):
            initialize(self.client, self.directory, ["reader@example.test"])
        self.assertIn("123456", (self.directory / "identity-policy.json").read_text())

    def test_rejects_wildcard_or_wrong_callback_before_writing(self):
        for email in ("*@example.test", "*", "a@example.test\nb@example.test"):
            with self.assertRaises(ValueError):
                initialize(self.client, self.directory, [email])
            self.assertFalse(self.directory.exists())
        web = json.loads(self.client.read_text())
        web["web"]["redirect_uris"] = ["http://other.test/oauth2/callback"]
        self.client.write_text(json.dumps(web))
        with self.assertRaises(ValueError):
            initialize(self.client, self.directory, ["reader@example.test"])
        self.assertFalse(self.directory.exists())


if __name__ == "__main__":
    unittest.main()
