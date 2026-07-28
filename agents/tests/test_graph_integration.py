from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps"))

from agents.graph import build_qa_graph  # noqa: E402
from agents.schemas import KnowledgeItemSchema, KnowledgeResult, QAAnswer  # noqa: E402
from worker.retrieval.retriever import HybridRetriever  # noqa: E402
from worker.schemas import Chunk  # noqa: E402


class FakeModelGateway:
    async def invoke_structured(
        self,
        *,
        output_schema: type,
        **_: Any,
    ) -> SimpleNamespace:
        if output_schema is KnowledgeResult:
            output = KnowledgeResult(
                sufficient=True,
                reason="sufficient",
                knowledge_items=[
                    KnowledgeItemSchema(
                        fact="Transactions provide isolation.",
                        source_ref_ids=["chunk-1"],
                    )
                ],
                selected_source_ref_ids=["chunk-1"],
                public_summary="证据充分",
            )
        elif output_schema is QAAnswer:
            output = QAAnswer(
                answer="Transactions provide isolation.",
                source_ref_ids=["chunk-1"],
                public_summary="回答已完成引用核验",
            )
        else:
            raise AssertionError(f"unexpected output schema: {output_schema}")
        return SimpleNamespace(output=output)


class QaGraphIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_compiled_graph_uses_real_hybrid_retriever_contract(self) -> None:
        retriever = HybridRetriever()
        await retriever.index_chunks(
            [
                Chunk(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    page_from=3,
                    page_to=3,
                    content="database transaction isolation",
                    section_path=["ch-03"],
                )
            ],
            [[1.0] + [0.0] * 127],
        )
        await retriever.set_doc_names({"doc-1": "database.pdf"})

        graph = build_qa_graph().compile()
        result = await graph.ainvoke(
            {
                "run_id": "run-1",
                "trace_id": "trace-1",
                "thread_id": "thread-1",
                "user_id": "user-1",
                "mode": "qa",
                "user_input": "database transaction isolation",
                "filters": {"chapter_ids": ["ch-03"]},
                "model_calls": 0,
                "node_hops": 0,
                "retry_count": 0,
            },
            config={
                "configurable": {
                    "model": FakeModelGateway(),
                    "retriever": retriever,
                }
            },
        )

        self.assertEqual(
            result["public_response"],
            "Transactions provide isolation.",
            result,
        )
        self.assertEqual(result["evidence"][0]["chunk_id"], "chunk-1")
        self.assertEqual(result["evidence"][0]["document_name"], "database.pdf")
        self.assertEqual(result["evidence"][0]["page_number"], 3)


if __name__ == "__main__":
    unittest.main()
