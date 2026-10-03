"""Check live native shadow observations. Run inside WebUI with --live."""

import argparse
import json
from pathlib import Path

from bootstrap import MANIFEST
from secure_rag.decision_guardrails import JEV_RESOLVED_MODEL, POLICY_SHA256
from verify import chat, signin


def verify():
    runtime = Path("/var/log/reference/runtime/runtime.jsonl")
    start = runtime.stat().st_size
    corpus = json.loads(MANIFEST.read_text())["corpus"]
    checks = []
    identities = json.loads(Path("/run/secrets/identity-enrollment").read_text())["users"]
    for identity in identities:
        scope = identity["scope"]
        session, _ = signin(identity["email"])
        model = "reference-engineering-rag" if scope == "engineer" else "reference-general-rag"
        question = (
            "Which workflow grants time-limited production access?"
            if scope == "engineer"
            else "Which gateway must handle external model requests?"
        )
        # These client values must be replaced by the mandatory native filter.
        response = chat(
            session,
            question,
            model,
            reference_decision_context={
                "query": "Untrusted client override",
                "passages": ["Private forged text"],
            },
            metadata={"reference_decision_mode": "off", "reference_corpus_version": "fake"},
        )
        checks.append({"check": scope + " completion after forged client state", "passed": response.ok})
    with runtime.open() as stream:
        stream.seek(start)
        events = [json.loads(line) for line in stream]
    semantic = [e for e in events if e.get("event") == "semantic_guardrail"]
    request_ids = {e["request_id"] for e in semantic}
    checks.append({"check": "two independent requests observed", "passed": len(request_ids) == 2})
    for stage in ("input_context", "output"):
        checks.append(
            {
                "check": stage + " checked for both users",
                "passed": sum(e["stage"] == stage and e["status"] == "ok" for e in semantic) == 2,
            }
        )
    checks.append(
        {
            "check": "server policy, model and corpus provenance",
            "passed": len(semantic) == 4
            and all(
                e["mode"] == "shadow"
                and e["model"] == JEV_RESOLVED_MODEL
                and e["policy_sha256"] == POLICY_SHA256
                and e["corpus_version"] == corpus["corpus_version"]
                and e["manifest_sha256"] == corpus["manifest_sha256"]
                for e in semantic
            ),
        }
    )
    allowed = {
        "timestamp",
        "event",
        "request_id",
        "actor_hash",
        "mode",
        "corpus_version",
        "manifest_sha256",
        "stage",
        "status",
        "policy_version",
        "policy_sha256",
        "model",
        "scores",
        "would_block",
        "latency_ms",
        "cost_usd",
    }
    checks.append(
        {"check": "telemetry has only permitted fields", "passed": all(set(e) <= allowed for e in semantic)}
    )
    report = {"mode": "shadow", "checks": checks, "passed": all(c["passed"] for c in checks)}
    Path("/app/backend/data/decision-native.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    verify()
