"""Versioned synthetic Russian audio fixtures using the installed macOS Milena voice.

Operator-only generator; generated audio stays in .local. The original eSpeak
stress suite is retained. These artifacts are not included in the public video.
"""

import argparse
import json
import subprocess
from pathlib import Path


def generate(suite, output):
    for case in json.loads(suite.read_text())["cases"]:
        if case["kind"] != "audio" or case["language"] != "ru":
            continue
        intermediate = output / (case["id"] + ".aiff")
        subprocess.run(  # noqa: S603 - fixed local fixture generator, no shell
            ["/usr/bin/say", "-v", "Milena", "-r", "150", "-o", str(intermediate), case["text"]], check=True
        )
        subprocess.run(  # noqa: S603 - fixed local fixture generator, no shell
            [
                "/opt/homebrew/bin/ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(intermediate),
                "-ar",
                "16000",
                "-ac",
                "1",
                str(output / (case["id"] + ".wav")),
            ],
            check=True,
        )
        intermediate.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.suite, args.output)
