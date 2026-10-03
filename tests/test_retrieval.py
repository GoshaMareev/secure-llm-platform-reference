from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "rag-assistant"))

from secure_rag.authorization import RetrievalScope  # noqa: E402
from secure_rag.gateway import DemoGateway  # noqa: E402
from secure_rag.retrieval import Retriever, load_glossary  # noqa: E402
from secure_rag.service import RAGService  # noqa: E402

from ingestion.build_index import build  # noqa: E402
from ingestion.corpus import release  # noqa: E402
from ingestion.store import write_index  # noqa: E402


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.index_path = Path(self.temporary.name) / "index.json"
        write_index(
            self.index_path,
            build(ROOT / "sample-data"),
            source_label="sample-data",
            corpus=release(ROOT / "sample-data"),
        )
        glossary = load_glossary(ROOT / "sample-data" / "glossary.json")
        self.retriever = Retriever(self.index_path, glossary=glossary)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_metadata_scope_applies_before_ranking(self) -> None:
        results = self.retriever.search(
            "approved model gateway",
            filters={"system": "ai"},
            scope=RetrievalScope(frozenset({"all", "engineers"})),
        )
        self.assertTrue(results)
        self.assertTrue(all(result.chunk.metadata["system"] == "ai" for result in results))

    def test_relevant_question_returns_expected_source(self) -> None:
        results = self.retriever.search(
            "Who approves emergency break-glass access?",
            scope=RetrievalScope(frozenset({"all", "engineers"})),
        )
        self.assertEqual(results[0].chunk.document_id, "access-control")

    def test_unknown_question_refuses(self) -> None:
        service = RAGService(self.retriever, DemoGateway(), min_confidence=0.34, top_k=3)
        answer = service.ask(
            "What is the parental leave allowance?", scope=RetrievalScope(frozenset({"all", "engineers"}))
        )
        self.assertTrue(answer.refused)
        self.assertEqual(answer.citations, ())

    def test_citations_are_unique_per_document(self) -> None:
        service = RAGService(self.retriever, DemoGateway(), min_confidence=0.34, top_k=3)
        answer = service.ask(
            "What happens during an AI service incident?",
            scope=RetrievalScope(frozenset({"all", "engineers"})),
        )
        source_ids = [citation["source_id"] for citation in answer.citations]
        self.assertEqual(source_ids, list(dict.fromkeys(source_ids)))


if __name__ == "__main__":
    unittest.main()
