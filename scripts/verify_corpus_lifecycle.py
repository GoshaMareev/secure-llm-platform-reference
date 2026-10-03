"""Run inside isolated native WebUI: interrupted upgrade, retry, stale model and rollback."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from bootstrap import MANIFEST, SOURCE, Operator, provision, verify_corpus
from verify import chat, signin

from ingestion.corpus import release
from ingestion.native_release import source_for


def verify(report):
    checks = []
    identities = Path("/run/secrets/identity-enrollment")
    provision(identities, "1.0.0")
    original = json.loads(MANIFEST.read_text())
    try:
        provision(identities, "1.1.0", interrupt_after=1)
    except ValueError as error:
        checks.append(
            {
                "check": "interrupted upload does not activate a release",
                "passed": str(error).startswith("Operator-requested")
                and json.loads(MANIFEST.read_text()) == original,
            }
        )
    provision(identities, "1.1.0")
    upgraded = json.loads(MANIFEST.read_text())
    provision(identities, "1.1.0")
    checks.append(
        {
            "check": "retry and repeated bootstrap retain stable file/collection IDs",
            "passed": upgraded == json.loads(MANIFEST.read_text()),
        }
    )
    operator = Operator()
    models = operator.call("GET", "/api/v1/models/all")
    model = next(m for m in models if m["id"] == "reference-general-rag")
    definition = {k: model[k] for k in ["id", "base_model_id", "name", "params", "meta", "access_grants"]}
    definition["meta"] = {**definition["meta"], "reference_manifest_sha256": "0" * 64}
    operator.call("POST", "/api/v1/models/model/update?id=reference-general-rag", json=definition)
    enrolled = json.loads(identities.read_text())["users"]
    reader, _ = signin(next(u["email"] for u in enrolled if u["scope"] == "reader"))
    reader.get("http://127.0.0.1:8080/api/models?refresh=true", timeout=30)
    response = chat(reader, "Which models are approved?")
    checks.append(
        {
            "check": "stale native model fails closed before inference",
            "passed": response.status_code == 400
            and response.json().get("detail", {}).get("verdict") == "corpus_version_mismatch",
        }
    )
    provision(identities, "1.1.0")
    with tempfile.TemporaryDirectory() as temporary:
        copy = Path(temporary) / "source"
        shutil.copytree(SOURCE, copy)
        target = copy / "documents/access-control.md"
        target.write_text(target.read_text() + "\nTampered synthetic fact.\n")
        try:
            release(copy)
            passed = False
        except ValueError:
            passed = True
        checks.append({"check": "changed bytes cannot reuse frozen manifest", "passed": passed})
    provision(identities, "1.0.0")
    rolled = json.loads(MANIFEST.read_text())
    verify_corpus(operator, rolled, release(source_for("1.0.0", SOURCE)))
    checks.append(
        {
            "check": "1.0.0 -> 1.1.0 -> 1.0.0 restores original IDs and bytes",
            "passed": rolled["corpus"] == original["corpus"]
            and rolled["files"] == original["files"]
            and rolled["knowledge"] == original["knowledge"],
        }
    )
    # Old/new data remain present for repeated rollbacks.
    verify_corpus(operator, upgraded, release(SOURCE))
    checks.append({"check": "retired collections remain available to operator for rollback", "passed": True})
    result = {
        "schema_version": 1,
        "profile": "isolated native pgvector + synthetic embedding/rerank/chat",
        "releases": {
            c["corpus_version"]: c["manifest_sha256"] for c in [original["corpus"], upgraded["corpus"]]
        },
        "checks": checks,
        "accepted": all(c["passed"] for c in checks),
    }
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["accepted"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if verify(args.report) else 1)
