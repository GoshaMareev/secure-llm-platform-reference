"""Isolated real-media candidate verification, with no provider credentials."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from verify_full_stack_config import DOCKER, ROOT, model


def run(output, russian_voice):
    if (ROOT / ".local").resolve() not in output.resolve().parents:
        raise ValueError("Evidence must remain in .local")
    if (output / "report.json").exists():
        raise ValueError("Never overwrite a media measurement")
    output.mkdir(parents=True, exist_ok=True)
    fixtures = output / "fixtures"
    fixtures.mkdir(exist_ok=True)
    config = model()
    project = "media-expanded-" + uuid.uuid4().hex[:10]
    services = {
        n: config["services"][n] for n in ("presidio-analyzer", "presidio-anonymizer", "media-inspector")
    }
    for service in services.values():
        service.pop("profiles", None)
        service["ports"] = []
        service["networks"] = {"platform": None}
    services["media-inspector"].setdefault("environment", {})["REFERENCE_RU_MEDIA_ENABLED"] = "true"

    def call(*args):
        subprocess.run(  # noqa: S603 - fixed Docker commands and local synthetic mounts
            [DOCKER, *args], check=True, cwd=ROOT
        )

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "compose.json"
        path.write_text(json.dumps({"services": services, "networks": {"platform": {"internal": True}}}))
        compose = ["compose", "-p", project, "-f", str(path)]
        try:
            call(*compose, "up", "-d", "--build", "--wait")
            call(
                "build",
                "--target",
                "fixtures",
                "-f",
                "apps/media-inspector/Dockerfile",
                "-t",
                "reference-expanded-media-fixtures",
                ".",
            )
            common = [
                "run",
                "--rm",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--tmpfs",
                "/tmp:size=64m,mode=1777",  # noqa: S108 - isolated container tmpfs
            ]
            call(
                *common,
                "--network",
                "none",
                "--entrypoint",
                "python",
                "--mount",
                f"type=bind,src={ROOT / 'scripts/generate_expanded_media.py'},dst=/generate.py,readonly",
                "--mount",
                f"type=bind,src={ROOT / 'evals/media-cases.json'},dst=/suite.json,readonly",
                "--mount",
                f"type=bind,src={fixtures},dst=/fixtures",
                "reference-expanded-media-fixtures",
                "/generate.py",
                "--suite",
                "/suite.json",
                "--output",
                "/fixtures",
            )
            if russian_voice == "milena":
                subprocess.run(  # noqa: S603 - fixed local fixture generator, no shell
                    [
                        sys.executable,
                        str(ROOT / "scripts/generate_russian_speech.py"),
                        "--suite",
                        str(ROOT / "evals/media-cases.json"),
                        "--output",
                        str(fixtures),
                    ],
                    check=True,
                )
            physical = {
                f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(fixtures.iterdir())
                if f.suffix in {".png", ".wav"}
            }
            (output / "physical-manifest.json").write_text(
                json.dumps(
                    {
                        "generator": "eSpeak-ng EN + macOS Milena RU"
                        if russian_voice == "milena"
                        else "eSpeak-ng EN/RU",
                        "os": platform.platform(),
                        "fixtures": physical,
                    },
                    indent=2,
                )
                + "\n"
            )
            call(
                *common,
                "--network",
                project + "_platform",
                "--entrypoint",
                "python",
                "-e",
                "PYTHONPATH=/reference:/reference/secure-rag",
                "-e",
                "PRESIDIO_ANALYZER_URL=http://presidio-analyzer:3000",
                "-e",
                "PRESIDIO_ANONYMIZER_URL=http://presidio-anonymizer:3000",
                "--mount",
                f"type=bind,src={ROOT / 'apps/rag-assistant'},dst=/reference/secure-rag,readonly",
                "--mount",
                f"type=bind,src={ROOT / 'ingestion'},dst=/reference/ingestion,readonly",
                "--mount",
                f"type=bind,src={ROOT / 'scripts/verify_expanded_media.py'},dst=/verify.py,readonly",
                "--mount",
                f"type=bind,src={ROOT / 'evals/media-cases.json'},dst=/suite.json,readonly",
                "--mount",
                f"type=bind,src={fixtures},dst=/fixtures,readonly",
                "--mount",
                f"type=bind,src={output},dst=/evidence",
                config["services"]["litellm"]["image"],
                "/verify.py",
                "--suite",
                "/suite.json",
                "--fixtures",
                "/fixtures",
                "--report",
                "/evidence/report.json",
            )
        finally:
            call(*compose, "down", "--volumes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--russian-voice", choices=["espeak", "milena"], default="espeak")
    args = parser.parse_args()
    run(args.output, args.russian_voice)
