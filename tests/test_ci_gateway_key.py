"""Exercise mask registration order and the downstream environment contract."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ci_gateway_key import main  # noqa: E402


class GatewayKeyTests(unittest.TestCase):
    def test_mask_is_flushed_before_environment_is_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = Path(directory) / "github-env"
            environment.write_text("EXISTING=value\n")

            class RunnerOutput(io.StringIO):
                def flush(output):
                    self.assertEqual(environment.read_text(), "EXISTING=value\n")
                    self.assertRegex(output.getvalue(), r"^::add-mask::sk-[0-9a-f]{48}\n$")
                    super().flush()

            output = RunnerOutput()
            with patch.dict(os.environ, {"GITHUB_ENV": str(environment)}), contextlib.redirect_stdout(output):
                main()
            key = output.getvalue().removeprefix("::add-mask::").rstrip("\n")
            self.assertEqual(environment.read_text(), f"EXISTING=value\nLITELLM_MASTER_KEY={key}\n")


if __name__ == "__main__":
    unittest.main()
