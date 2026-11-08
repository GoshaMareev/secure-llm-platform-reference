from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pre_publication_check import SYNTHETIC_PEM_LITERAL, SYNTHETIC_PEM_PATHS, scan_text  # noqa: E402


class PublicationCheckTests(unittest.TestCase):
    def test_detects_private_key_formats_without_echoing_material(self) -> None:
        for kind in ("", "ENCRYPTED ", "RSA ", "OPENSSH ", "EC ", "DSA ", "PGP "):
            with self.subTest(kind=kind):
                header = "-----BEGIN " + kind + "PRIVATE KEY-----"
                text = header + "\nNonfunctionalTestMaterial\n"
                self.assertEqual(
                    scan_text(ROOT / "probe.txt", text, ()),
                    ["probe.txt:1: matched private-key"],
                )

    def test_accepts_public_keys_and_certificates(self) -> None:
        for kind in ("PUBLIC KEY", "RSA PUBLIC KEY", "CERTIFICATE"):
            with self.subTest(kind=kind):
                self.assertEqual(scan_text(ROOT / "probe.txt", "-----BEGIN " + kind + "-----", ()), [])

    def test_only_exact_known_synthetic_pem_literal_is_exempt(self) -> None:
        header = "-----BEGIN " + "PRIVATE KEY-----"
        for relative in SYNTHETIC_PEM_PATHS:
            with self.subTest(path=relative):
                path = ROOT / relative
                self.assertEqual(scan_text(path, "sample = " + SYNTHETIC_PEM_LITERAL, ()), [])
                for text in (
                    SYNTHETIC_PEM_LITERAL.replace("SYNTHETIC", "NonfunctionalTestMaterial"),
                    SYNTHETIC_PEM_LITERAL.replace("END", "BROKEN"),
                    SYNTHETIC_PEM_LITERAL + " " + header,
                    header + " " + SYNTHETIC_PEM_LITERAL,
                    SYNTHETIC_PEM_LITERAL + "\n" + header,
                ):
                    self.assertTrue(scan_text(path, text, ()))
                # Other secret rules and the private denylist still see the full line.
                self.assertTrue(scan_text(path, SYNTHETIC_PEM_LITERAL + " ghp_" + "a" * 30, ()))
                self.assertTrue(scan_text(path, SYNTHETIC_PEM_LITERAL, ("synthetic",)))
                self.assertEqual(scan_text(path, SYNTHETIC_PEM_LITERAL, (), prefix="history:abc:"), [])
        self.assertTrue(scan_text(ROOT / "other.py", SYNTHETIC_PEM_LITERAL, ()))

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
