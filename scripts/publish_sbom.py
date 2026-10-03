"""Publish Syft CycloneDX inventories; supplement pinned lock/model artifacts explicitly."""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def publish(source, output, artifacts=None):
    output.mkdir(parents=True, exist_ok=True)
    images = json.loads((source / "images.json").read_text())
    rows = []
    index = []
    for path in sorted(source.glob("*.json")):
        if path.name == "images.json":
            continue
        # Syft may embed the source directory in component/property names.
        raw = path.read_text().replace(str(ROOT), "workspace/secure-llm-platform-reference")
        raw = raw.replace(str(ROOT.parent / "living-portfolio"), "workspace/living-portfolio")
        document = json.loads(raw)
        if document.get("bomFormat") != "CycloneDX":
            raise ValueError("Expected CycloneDX")
        if path.name == "application.json":
            # Syft directory scan does not recognize .lock as requirements.txt.
            # Keep that limitation visible and supplement immutable lock versions.
            seen = set()
            for lock in [
                ROOT / "requirements.lock",
                ROOT / "apps/media-inspector/requirements.lock",
                ROOT / "infra/presidio/requirements-ru.lock",
            ]:
                for name, version in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock.read_text(), re.M):
                    if (name, version) in seen:
                        continue
                    seen.add((name, version))
                    document.setdefault("components", []).append(
                        {
                            "type": "library",
                            "name": name,
                            "version": version,
                            "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
                            "properties": [
                                {
                                    "name": "reference:provenance",
                                    "value": "operator supplement from " + str(lock.relative_to(ROOT)),
                                },
                                {
                                    "name": "reference:license-review",
                                    "value": "unconfirmed in lock; consult matching container inventory",
                                },
                            ],
                        }
                    )
        if artifacts and path.name == "application.json":
            manifest = json.loads(artifacts.read_text())
            files = [
                ("asr/" + name, manifest["asr"]["revision"], sha)
                for name, sha in manifest["asr"]["files"].items()
            ]
            files += [
                ("ocr/" + row["file"], "installed image artifact", row["sha256"]) for row in manifest["ocr"]
            ]
            for name, version, sha in files:
                document.setdefault("components", []).append(
                    {
                        "type": "file",
                        "name": name,
                        "version": version,
                        "hashes": [{"alg": "SHA-256", "content": sha}],
                        "properties": [
                            {
                                "name": "reference:provenance",
                                "value": "verified model/language artifact inventory",
                            }
                        ],
                    }
                )
            ru = manifest["russian_pipeline"]
            document["components"].append(
                {
                    "type": "library",
                    "name": ru["name"],
                    "version": ru["version"],
                    "hashes": [{"alg": "SHA-256", "content": ru["wheel_sha256"]}],
                    "licenses": [{"license": {"id": "MIT"}}],
                    "properties": [
                        {
                            "name": "reference:provenance",
                            "value": "official Russian wheel checksum verified before install",
                        }
                    ],
                }
            )
        target = output / path.name
        target.write_text(json.dumps(document, separators=(",", ":")) + "\n")
        for component in document.get("components", []):
            licenses = []
            for item in component.get("licenses", []):
                value = (
                    item.get("expression")
                    or item.get("license", {}).get("id")
                    or item.get("license", {}).get("name")
                )
                if value:
                    licenses.append(value)
            rows.append(
                {
                    "inventory": target.name,
                    "package": component["name"],
                    "version": component.get("version", "unconfirmed"),
                    "licenses": " | ".join(licenses) or "UNCONFIRMED",
                    "purl": component.get("purl", ""),
                }
            )
        index.append(
            {
                "file": target.name,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "components": len(document.get("components", [])),
                "image": images[int(path.stem.split("-")[-1])]
                if path.stem.startswith("container-")
                else None,
            }
        )
    with (output / "licenses.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["inventory", "package", "version", "licenses", "purl"])
        writer.writeheader()
        writer.writerows(rows)
    (output / "index.json").write_text(
        json.dumps(
            {
                "syft_version": "1.54.0",
                "format": "CycloneDX JSON",
                "inventories": index,
                "license_review": {
                    "total_components": len(rows),
                    "unconfirmed": sum(r["licenses"] == "UNCONFIRMED" for r in rows),
                    "scope": "Metadata inventory; UNCONFIRMED means license evidence is absent, "
                    "not permission to redistribute.",
                },
            },
            indent=2,
        )
        + "\n"
    )
    print("Published inventories:", len(index), "components:", len(rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    publish(args.source, args.output, args.artifacts)
