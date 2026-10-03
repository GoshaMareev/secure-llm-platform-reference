"""Render the frozen bilingual media suite; synthetic pixels and speech only."""

import argparse
import json
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def generate(suite, output):
    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    for case in json.loads(suite.read_text())["cases"]:
        if case["kind"] == "image":
            lines = textwrap.wrap(case["text"], width=48)
            picture = Image.new("RGB", (1400, 100 + 60 * len(lines)), "white")
            draw = ImageDraw.Draw(picture)
            for i, line in enumerate(lines):
                draw.text((30, 35 + i * 60), line, font=font, fill="black")
            picture.save(output / (case["id"] + ".png"))
        else:
            subprocess.run(  # noqa: S603 - fixed TTS executable and frozen synthetic text
                [
                    "/usr/bin/espeak-ng",
                    "-v",
                    "ru" if case["language"] == "ru" else "en-us",
                    "-s",
                    "140",
                    "-w",
                    str(output / (case["id"] + ".wav")),
                    case["text"],
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.suite, args.output)
