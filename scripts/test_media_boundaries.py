"""Reproduce synthetic OCR/STT privacy checks without hosted inference or keys.

Default: an isolated Compose project, removed after verification. A running
private stack can instead be reused with --network (its services are untouched).
Only the build downloads public packages/model weights; test containers have
no internet access. Fixtures and the metadata-only report stay under .local.
"""

import argparse
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from verify_full_stack_config import DOCKER, ROOT, model


def command(args, **kwargs):
    subprocess.run([DOCKER, *args], check=True, cwd=ROOT, **kwargs)  # noqa: S603


def verify(output, network=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixtures = output / "fixtures"
    fixtures.mkdir(exist_ok=True)
    config = model()
    project = "media-check-" + uuid.uuid4().hex[:12]
    fixture_image = project + "-fixtures"
    with tempfile.TemporaryDirectory(prefix="reference-media-") as temporary:
        config_path = Path(temporary, "compose.json")
        services = {
            name: config["services"][name]
            for name in ("media-inspector", "presidio-analyzer", "presidio-anonymizer")
        }
        for service in services.values():
            service.pop("profiles", None)
            service["ports"] = []
            service["networks"] = {"platform": None}
        config_path.write_text(
            json.dumps({"services": services, "networks": {"platform": {"internal": True}}})
        )
        compose = ["compose", "--project-name", project, "-f", str(config_path)]
        owned = network is None
        try:
            if owned:
                command([*compose, "up", "-d", "--build", "--wait"])
                network = project + "_platform"
            command([
                "build", "--target", "fixtures", "-f", "apps/media-inspector/Dockerfile",
                "-t", fixture_image, ".",
            ])
            command([
                "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--user", f"{os.getuid()}:{os.getgid()}",
                "--tmpfs", "/tmp:size=64m,mode=1777",  # noqa: S108 - isolated container memory
                "--mount", f"type=bind,src={fixtures},dst=/fixtures", fixture_image,
            ])
            run = [
                "run", "--rm", "--network", network, "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--user", f"{os.getuid()}:{os.getgid()}",
                "--tmpfs", "/tmp:size=256m,mode=1777",  # noqa: S108 - isolated container memory
                "--entrypoint", "python",
                "-e", "PYTHONPATH=/reference:/reference/secure-rag",
                "-e", "REFERENCE_DECISION_MODE=off",
                "-e", "PRESIDIO_ANALYZER_URL=http://presidio-analyzer:3000",
                "-e", "PRESIDIO_ANONYMIZER_URL=http://presidio-anonymizer:3000",
                "-e", "GLOBAL_LOG_LEVEL=ERROR",
            ]
            for source, target, readonly in (
                (ROOT / "apps/rag-assistant", "/reference/secure-rag", True),
                (ROOT / "ingestion", "/reference/ingestion", True),
                (ROOT / "gateway/reference_gateway.py", "/reference/reference_gateway.py", True),
                (ROOT / "scripts/verify_media.py", "/reference/verify_media.py", True),
                (fixtures, "/fixtures", True),
                (output, "/evidence", False),
            ):
                run.extend([
                    "--mount", f"type=bind,src={source},dst={target}" + (",readonly" if readonly else "")
                ])
            command([
                *run, config["services"]["litellm"]["image"],
                "/reference/verify_media.py", "--report", "/evidence/report.json",
            ])
        finally:
            if owned:
                command([*compose, "down", "--volumes"])
            subprocess.run([DOCKER, "image", "rm", fixture_image], capture_output=True)  # noqa: S603


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/media-evaluation")
    parser.add_argument("--network", help="Reuse a private Compose network; leave its services running")
    args = parser.parse_args()
    verify(args.output, args.network)
