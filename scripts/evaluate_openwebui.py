"""Run the versioned quality suite through native Knowledge and the guarded gateway.

Execute inside Open WebUI. --live explicitly enables hosted model/embedding/rerank
calls. Reports retain metrics and source IDs, never identities, tokens or raw answers.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests
from bootstrap import MANIFEST, SOURCE, Operator, verify_corpus
from verify import chat, signin

from evals.quality import (
    Observation,
    acceptance,
    diagnostic_path,
    gate,
    load_cases,
    markdown,
    observe_native,
    report,
    score,
)
from ingestion.corpus import release


def evaluate(args):
    corpus = release(SOURCE)
    manifest = json.loads(MANIFEST.read_text())
    operator = Operator()
    verify_corpus(operator, manifest, corpus)
    suite = load_cases(args.cases, corpus)
    sessions = {}
    for identity in json.loads(Path("/run/secrets/identity-enrollment").read_text())["users"]:
        sessions[identity["scope"]], _ = signin(identity["email"])
    # Record the actual operator-managed model and retrieval settings.
    models = operator.call("GET", "/api/v1/models/all")
    selected = [m for m in models if m["id"] in {"reference-general-rag", "reference-engineering-rag"}]
    if len(selected) != 2 or any(
        m["meta"].get("reference_manifest_sha256") != corpus["manifest_sha256"] for m in selected
    ):
        raise ValueError("Native model definitions target different corpus")
    for model in selected:
        scopes = ("General", "Engineering") if model["id"] == "reference-engineering-rag" else ("General",)
        if {k["id"] for k in model["meta"]["knowledge"]} != {manifest["knowledge"][s] for s in scopes}:
            raise ValueError("Native model Knowledge scope differs from release")
    source_hashes = {
        name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for name, path in (
            ("gateway", "/reference/litellm.yaml"),
            ("policy", "/reference/reference_filter.py"),
            ("rerank", "/reference/reference_rerank.py"),
            ("runner", __file__),
        )
    }
    rows = []
    traces = []
    selected_cases = [c for c in suite["cases"] if not args.group or c.get("group", "core") in args.group]
    for case in selected_cases:
        start = time.monotonic()
        try:
            response = chat(
                sessions[case["actor"]],
                case["question"],
                model=(
                    "reference-engineering-rag" if case["actor"] == "engineer" else "reference-general-rag"
                ),
                messages=[*case.get("history", []), {"role": "user", "content": case["question"]}],
            )
            observation = observe_native(response, corpus, case)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            observation = Observation("", [], [], False, False, error=True)
        if args.diagnostics:
            traces.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "answer": observation.text,
                    "sources": observation.sources,
                    "error": observation.error,
                    "raw_sources": response.json().get("sources", [])
                    if "response" in locals() and response.status_code == 200
                    else [],
                }
            )
        observation.latency_ms = (time.monotonic() - start) * 1000
        rows.append(score(case, observation))
        print(f"{case['id']}: {'pass' if rows[-1]['passed'] else 'FAIL'}", file=sys.stderr, flush=True)
    verify_corpus(operator, manifest, corpus)
    if release(SOURCE) != corpus or json.loads(MANIFEST.read_text()) != manifest:
        raise ValueError("Corpus changed during benchmark")
    configuration = {
        "source_commit": os.environ.get("REFERENCE_SOURCE_COMMIT"),
        "runtime_sha256": json.loads(os.environ.get("REFERENCE_RUNTIME_HASHES", "{}")),
        "models": [
            {"id": m["id"], "base_model_id": m["base_model_id"], "params": m["params"]} for m in selected
        ],
        "retrieval": {
            k: os.environ.get(k)
            for k in (
                "RAG_EMBEDDING_MODEL",
                "RAG_RERANKING_MODEL",
                "RAG_TOP_K",
                "RAG_TOP_K_RERANKER",
                "RAG_RELEVANCE_THRESHOLD",
                "ENABLE_RAG_HYBRID_SEARCH",
                "ENABLE_RETRIEVAL_QUERY_GENERATION",
            )
        },
        "configuration_sha256": source_hashes,
        "pii_backend": "presidio",
        "citation_format": "native numeric source IDs",
    }
    if args.diagnostics:
        diagnostic_path(args.diagnostics).write_text(json.dumps(traces, ensure_ascii=False, indent=2) + "\n")
    return report(rows, corpus, suite, backend="native-openwebui", configuration=configuration)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cases", type=Path, default=Path("/reference/evals/quality-cases.json"))
    parser.add_argument("--report", type=Path, default=Path("/app/backend/data/quality-native.json"))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--group", action="append", choices=["core", "development", "holdout"])
    parser.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("Native quality evaluation needs --live to enable hosted calls")
    try:
        if args.diagnostics:
            diagnostic_path(args.diagnostics)
        result = evaluate(args)
        baseline = json.loads(args.baseline.read_text()) if args.baseline else None
        failures = gate(result, baseline)
        suite = load_cases(args.cases, release(SOURCE))
        if not args.group:
            failures += acceptance(result, suite)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
        args.report.with_suffix(".md").write_text(markdown(result))
        print(json.dumps({"metrics": result["metrics"], "gate_failures": failures}, indent=2))
        # A live run measures quality strictly: every reference case must pass.
        core_failures = [r for r in result["cases"] if r.get("group", "core") == "core" and not r["passed"]]
        raise SystemExit(1 if failures or core_failures else 0)
    except (requests.RequestException, OSError, ValueError, KeyError):
        if args.diagnostics:
            import traceback

            diagnostic_path(args.diagnostics.with_suffix(".error.txt")).write_text(traceback.format_exc())
        print("Native quality preflight failed; sensitive details omitted.", file=sys.stderr)
        raise SystemExit(1) from None
