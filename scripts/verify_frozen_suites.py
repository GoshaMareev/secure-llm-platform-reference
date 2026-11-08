"""Verify pre-measurement artifact fingerprints and fixed acceptance thresholds."""

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify():
    registry = json.loads((ROOT / "evals/frozen-suites.json").read_text())
    for name, expected in registry["artifacts"].items():
        if hashlib.sha256((ROOT / "evals" / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Frozen benchmark changed: " + name)
    quality = json.loads((ROOT / "evals/quality-expanded.json").read_text())
    counts = Counter(c.get("group", "core") for c in quality["cases"])
    if counts != {"core": 32, "development": 64, "holdout": 32}:
        raise ValueError("Frozen quality split changed")
    if Counter(c["language"] for c in quality["cases"] if c["group"] == "holdout") != {"en": 16, "ru": 16}:
        raise ValueError("Holdout language split changed")
    original = json.loads((ROOT / "evals/quality-core-1.0.0.json").read_text())["cases"]
    core = [
        {k: v for k, v in c.items() if k not in {"group", "language"}}
        for c in quality["cases"]
        if c["group"] == "core"
    ]
    if core != original:
        raise ValueError("Original core cases must remain unchanged")
    for name in [registry["active_decision_suite"], "media-cases.json"]:
        cases = json.loads((ROOT / "evals" / name).read_text())["cases"]
        if len({c["id"] for c in cases}) != len(cases):
            raise ValueError("Duplicate frozen IDs")
    print("Frozen quality, media and decision suites verified.")


if __name__ == "__main__":
    verify()
