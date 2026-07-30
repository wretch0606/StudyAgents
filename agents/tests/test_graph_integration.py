from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps"))

from worker.retrieval.retriever import HybridRetriever  # noqa: E402
from worker.schemas import Chunk  # noqa: E402

from agents.graph import build_qa_graph  # noqa: E402
from agents.schemas import (  # noqa: E402
    GeneratedQuestionPrivate,
    GradeResultPrivate,
    KnowledgeItemSchema,
    KnowledgeResult,
    QAAnswer,
    QuestionPrivate,
    RubricItem,
    StepScore,
)


class FakeModelGateway:
    """支持 QA 和 Practice 模式的 Fake 模型网关"""

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
        elif output_schema is GeneratedQuestionPrivate:
            output = GeneratedQuestionPrivate(
                question_id="q-test-001",
                source_kind="past_exam",
                question_type="choice",
                difficulty=2,
                stem="数据库管理系统的核心目标是什么？",
                options=[
                    {"id": "A", "text": "管理数据"},
                    {"id": "B", "text": "管理硬件"},
                    {"id": "C", "text": "管理网络"},
                    {"id": "D", "text": "管理系统"},
                ],
                knowledge_point_ids=["kp-001"],
                source_refs=[
                    {
                        "document_id": "doc-1",
                        "document_name": "database.pdf",
                        "page_number": 1,
                        "question_no": None,
                        "chunk_id": "chunk-1",
                        "excerpt": "数据库管理系统是用于管理数据的软件系统。",
                        "score": 0.95,
                    }
                ],
                private=QuestionPrivate(
                    expected_answer="A",
                    rubric=[
                        RubricItem(
                            id="R1",
                            description="选择正确选项",
                            max_score=5,
                            source_ref_ids=["chunk-1"],
                        )
                    ],
                ),
                confidence=0.95,
                public_summary="出题完成",
            )
        elif output_schema is GradeResultPrivate:
            output = GradeResultPrivate(
                score=5,
                max_score=5,
                step_scores=[
                    StepScore(
                        rubric_item_id="R1",
                        status="met",
                        score=5,
                        feedback="选择正确",
                    )
                ],
                explanation="回答正确",
                source_ref_ids=["chunk-1"],
                confidence=1.0,
                review_required=False,
                public_summary="评分完成",
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


class PracticeGraphIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Day 4 修复验证：训练图编译 + 执行 + 数据类引用 + 选择评分"""

    async def test_practice_graph_compiles_and_runs(self) -> None:
        """build_practice_graph() 可正常编译，不报 NameError/参数不匹配"""
        from agents.graph_practice import build_practice_graph

        graph = build_practice_graph().compile()
        self.assertIsNotNone(graph)

    async def test_practice_graph_coordinator_to_questioner(self) -> None:
        """训练图节点直调：dataclass SourceRef 兼容 + 公开题目防泄露"""
        from agents.graph_practice import coordinator_practice_node, questioner_node
        from agents.state import AgentState

        retriever = HybridRetriever()
        await retriever.index_chunks(
            [
                Chunk(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    page_from=1,
                    page_to=1,
                    content="数据库管理系统是用于管理数据的软件系统。",
                    section_path=["ch-01"],
                )
            ],
            [[1.0] + [0.0] * 127],
        )
        await retriever.set_doc_names({"doc-1": "database.pdf"})

        # 验证 retriever 返回的是数据类对象（真实类型，非 dict）
        real_result = await retriever.retrieve("数据库", filters=None, user_role="admin")
        self.assertGreater(len(real_result.source_refs), 0)
        ref0 = real_result.source_refs[0]
        self.assertTrue(hasattr(ref0, "document_name"), "SourceRef 应为数据类对象")

        # 验证 graph 可编译
        from agents.graph_practice import build_practice_graph
        graph = build_practice_graph().compile()
        self.assertIsNotNone(graph)

        state: AgentState = {
            "run_id": "run-1", "trace_id": "trace-1", "thread_id": "thread-1",
            "user_id": "u1", "mode": "practice", "user_input": "训练",
            "filters": {"chapter_ids": ["ch-01"], "difficulty": 2,
                        "question_types": ["choice"], "target_count": 1},
            "model_calls": 0, "node_hops": 0, "retry_count": 0,
            "current_item_index": 0, "practice_items": [],
            "exclude_chunk_ids": [], "practice_scores": [],
        }
        cfg = {"configurable": {"model": FakeModelGateway(), "retriever": retriever}}

        r1 = await coordinator_practice_node(state, cfg)
        self.assertEqual(r1["next_node"], "questioner")
        state.update(r1)
        r2 = await questioner_node(state, cfg)

        self.assertIn("current_public_question", r2)
        pub_q = r2["current_public_question"]
        self.assertEqual(pub_q["question_type"], "choice")
        self.assertNotIn("expected_answer", str(pub_q))
        items = r2.get("practice_items", [])
        self.assertEqual(len(items), 1)
        self.assertIn("private", items[0])
        self.assertEqual(items[0]["private"]["expected_answer"], "A")


    async def test_full_graph_two_questions_correct_choice(self) -> None:
        """Day 4 集成：完整状态图执行连续两题，正确选择取得非零满分"""
        from agents.graph_practice import build_practice_graph
        from agents.state import AgentState
        from agents.tests.fake_adapters import FakeModelGateway, FakeRetriever
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.types import Command

        graph = build_practice_graph().compile(checkpointer=MemorySaver())

        initial_state: AgentState = {
            "run_id": "run-full-1",
            "trace_id": "trace-full-1",
            "thread_id": "thread-full-1",
            "user_id": "user-1",
            "mode": "practice",
            "user_input": "开始训练",
            "filters": {
                "chapter_ids": ["ch-01"],
                "difficulty": 2,
                "question_types": ["choice"],
                "target_count": 2,
            },
            "model_calls": 0,
            "node_hops": 0,
            "retry_count": 0,
            "current_item_index": 0,
            "practice_items": [],
            "exclude_chunk_ids": [],
            "practice_scores": [],
        }

        config = {
            "configurable": {
                "thread_id": "thread-full-1",
                "model": FakeModelGateway(),
                "retriever": FakeRetriever(),
                "event_sink": None,
            }
        }

        # ── 第 1 题：coordinator → questioner → wait_for_answer（中断）──
        result = await graph.ainvoke(initial_state, config)

        # 验证第 1 题的公开题目
        pub_q1 = result.get("current_public_question", {})
        self.assertEqual(pub_q1.get("question_type"), "choice",
                        f"第1题应为选择题，实际: {pub_q1}")
        self.assertEqual(pub_q1.get("order_no"), 1,
                        f"第1题 order_no 应为 1，实际: {pub_q1.get('order_no')}")
        # 防泄露
        self.assertNotIn("expected_answer", str(pub_q1))
        self.assertNotIn("rubric", str(pub_q1))

        # ── 提交第 1 题答案 A（正确）→ evaluator → questioner（出第 2 题）──
        result2 = await graph.ainvoke(Command(resume="A"), config)

        # 验证第 1 题评分
        items = result2.get("practice_items", [])
        self.assertEqual(len(items), 2, f"应有 2 题记录，实际: {len(items)}")
        grade1 = items[0].get("grade", {})
        self.assertTrue(grade1.get("met", False),
                       f"第 1 题正确作答 met 应为 True，实际: {grade1}")
        # 关键断言：正确选择取得非零满分
        self.assertGreater(grade1.get("score", 0), 0,
                          f"第 1 题正确选择得分应 > 0，实际: {grade1.get('score')}")
        self.assertGreater(grade1.get("max_score", 0), 0,
                          f"第 1 题满分应 > 0，实际: {grade1.get('max_score')}")

        # 验证题号连续不跳跃
        pub_q2 = result2.get("current_public_question", {})
        self.assertEqual(pub_q2.get("order_no"), 2,
                        f"第 2 题 order_no 应为 2，实际: {pub_q2.get('order_no')}")

        # ── 提交第 2 题答案 B（错误）→ evaluator → summary（target_count=2 结束）──
        result3 = await graph.ainvoke(Command(resume="B"), config)

        # 验证训练总结
        summary = result3.get("practice_summary", {})
        self.assertIsNotNone(summary)
        self.assertEqual(summary.get("items_count"), 2,
                        f"总题数应为 2，实际: {summary.get('items_count')}")

        # 验证第 2 题评分（从 result3 读取——evaluator 在这一步运行）
        items3 = result3.get("practice_items", [])
        self.assertEqual(len(items3), 2,
                        f"最终应有 2 题记录，实际: {len(items3)}")
        grade2 = items3[1].get("grade", {})
        self.assertIsNotNone(grade2)
        self.assertFalse(grade2.get("met", True),
                        f"第 2 题错误作答 met 应为 False，实际: {grade2}")
        self.assertEqual(grade2.get("score", 1), 0,
                        f"第 2 题错误作答得分应为 0，实际: {grade2.get('score')}")

        # 验证总分（Q1 正确 5分 + Q2 错误 0分 = 5/10）
        self.assertEqual(summary.get("total_score", 0), 5,
                        f"总分应为 5（5+0），实际: {summary.get('total_score')}")
        self.assertEqual(summary.get("total_max", 0), 10,
                        f"总分上限应为 10（5+5），实际: {summary.get('total_max')}")

        # 验证公开响应无泄露
        pub_resp = result3.get("public_response", "")
        self.assertNotIn("expected_answer", pub_resp)
        self.assertIn("训练完成", pub_resp, "总结应包含 '训练完成'")

    async def test_choice_grading_max_score_zero(self) -> None:
        """选择题 max_score=0 时正确作答 met=True（Day 4 修复验证）"""
        from agents.rules.grading import grade_choice

        # 修复前：max_score=0 正确作答 → score=0 → met=False（bug）
        # 修复后：met 基于匹配判断，不受 max_score 影响
        r = grade_choice("A", "A", max_score=0)
        self.assertTrue(r["met"], "max_score=0 正确作答 met 应为 True")
        self.assertEqual(r["score"], 0)

        r2 = grade_choice("B", "A", max_score=10)
        self.assertFalse(r2["met"], "错误作答 met 应为 False")

        r3 = grade_choice("A", "A", max_score=5)
        self.assertTrue(r3["met"])
        self.assertEqual(r3["score"], 5)


if __name__ == "__main__":
    unittest.main()
