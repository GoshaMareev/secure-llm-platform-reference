"""Fetch a fixed, public model revision at image build time; verify LFS hashes."""

import hashlib
import json
import urllib.request
from pathlib import Path

REPO = "Systran/faster-whisper-small"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"
FILES = {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}


def main():
    root = Path("/models/whisper-small")
    root.mkdir(parents=True, exist_ok=True)
    metadata = f"https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true"
    with urllib.request.urlopen(metadata, timeout=30) as response:  # noqa: S310 - fixed HTTPS source
        info = json.load(response)
    if info["sha"] != REVISION:
        raise RuntimeError("Unexpected model revision")
    manifest = {"repo": REPO, "revision": REVISION, "files": {}}
    for file in info["siblings"]:
        name = file["rfilename"]
        if name not in FILES:
            continue
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=90) as response:  # noqa: S310 - public artifact, no credentials
            with (root / name).open("wb") as output:
                for chunk in iter(lambda: response.read(1_048_576), b""):
                    digest.update(chunk)
                    output.write(chunk)
        expected = file.get("lfs", {}).get("sha256")
        if expected and digest.hexdigest() != expected:
            raise RuntimeError("Model artifact checksum mismatch")
        manifest["files"][name] = digest.hexdigest()
    if set(manifest["files"]) != FILES:
        raise RuntimeError("Incomplete model snapshot")
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
