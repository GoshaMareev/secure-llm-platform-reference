from __future__ import annotations

import argparse
import json
from pathlib import Path

from secure_rag.gateway import DemoGateway
from secure_rag.retrieval import Retriever, load_glossary
from secure_rag.service import RAGService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic citation and refusal checks.")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()

    glossary = load_glossary(Path("sample-data/glossary.json"))
    service = RAGService(
        Retriever(args.index, glossary=glossary),
        DemoGateway(),
        min_confidence=0.34,
        top_k=3,
    )
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]

    passed = 0
    for case in cases:
        result = service.ask(case["question"], filters=case.get("filters"))
        source_ids = {citation["source_id"] for citation in result.citations}
        source_ok = case["expected_source"] is None or case["expected_source"] in source_ids
        refusal_ok = result.refused is bool(case["expect_refusal"])
        ok = source_ok and refusal_ok
        passed += int(ok)
        print(
            json.dumps(
                {
                    "case": case["id"],
                    "passed": ok,
                    "refused": result.refused,
                    "confidence": round(result.confidence, 4),
                    "sources": sorted(source_ids),
                },
                separators=(",", ":"),
            )
        )

    print(f"summary: {passed}/{len(cases)} passed")
    raise SystemExit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
