from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pre_publication_check import scan_text  # noqa: E402


class PublicationCheckTests(unittest.TestCase):
    def test_detects_google_oauth_secret_without_echoing_value(self) -> None:
        token = "GOCSPX-" + "a" * 28
        problems = scan_text(ROOT / "README.md", f"credential={token}", ())
        self.assertEqual(problems, ["README.md:1: matched google-oauth-secret"])
        self.assertNotIn(token, problems[0])

    def test_detects_token_without_echoing_value(self) -> None:
        token = "ghp_" + "a" * 30
        problems = scan_text(ROOT / "README.md", f"credential={token}", ())
        self.assertEqual(problems, ["README.md:1: matched github-token"])
        self.assertNotIn(token, problems[0])

    def test_detects_private_denylist_term(self) -> None:
        problems = scan_text(ROOT / "README.md", "Internal Project Aurora", ("project aurora",))
        self.assertEqual(problems, ["README.md:1: matched private denylist term #1"])

    def test_detects_windows_home_path_with_forward_slashes(self) -> None:
        windows_path = "C:" + "/" + "Users/" + "example/Documents/project"
        problems = scan_text(ROOT / "README.md", windows_path, ())
        self.assertEqual(problems, ["README.md:1: matched local-home-path"])


if __name__ == "__main__":
    unittest.main()
