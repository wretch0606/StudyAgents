"""Real AgentRunner — LangGraph 包装类，实现 AgentRunnerProtocol。

将 C 的 LangGraph 状态图（build_qa_graph / build_practice_graph）
适配为 D 的 AgentRunnerProtocol 接口。
"""

from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import UTC, datetime

# LangGraph 0.3 序列化配置：允许 core 类型避免 "mutable default" 错误
os.environ.setdefault("LANGGRAPH_ALLOWED_OBJECTS", "core")

from apps.api.services.agent_runner import AgentRunResult, AgentRunnerProtocol
from apps.api.services.checkpointer import get_checkpointer

logger = logging.getLogger(__name__)


class LangGraphAgentRunner:
    """真实的 AgentRunner：调用 LangGraph 状态图执行 Agent Run。

    依赖注入通过 LangGraph config["configurable"] 传递：
      - model:      ModelGateway 实例
      - event_sink: AgentEventSink 实例
      - retriever:  B 的 HybridRetriever 实例
    """

    async def run(
        self,
        *,
        run_id: str,
        trace_id: str,
        user_input: str,
        mode: str,
        model_gateway,
        event_sink,
        last_successful_node: str | None = None,
        checkpoint_ref: str | None = None,
    ) -> AgentRunResult:
        """执行一次 Agent Run。"""
        from agents.graph import build_qa_graph
        from agents.graph_practice import build_practice_graph
        from agents.state import AgentState

        start = datetime.now(UTC)

        # 选择状态图
        if mode == "practice":
            builder = build_practice_graph()
        else:
            builder = build_qa_graph()

        # 暂时不使用 checkpointer（LangGraph 0.3.34 对 TypedDict list 字段序列化有兼容问题）
        graph = builder.compile()

        # 构建初始状态
        initial_state: AgentState = {
            "run_id": run_id,
            "trace_id": trace_id,
            "thread_id": f"thread-{_uuid.uuid4().hex[:16]}",
            "user_id": "system",  # 由调用方通过 event_sink 的 db_session 确定
            "mode": mode,
            "user_input": user_input,
            "filters": {},
            "public_response": None,
            "model_calls": 0,
            "node_hops": 0,
            "retry_count": 0,
            "error": None,
            "normalized_query": user_input.strip(),
            "next_node": "",
            "sufficient": False,
            "reason": "",
            "evidence": [],
            "knowledge": [],
            "user_answer": None,
        }

        # 依赖注入（retriever 使用空实现，等待 B 接入后替换）
        config = {
            "configurable": {
                "thread_id": f"thread-{_uuid.uuid4().hex[:16]}",
                "model": model_gateway,
                "event_sink": event_sink,
                "retriever": _StubRetriever(),
            }
        }

        try:
            result = await graph.ainvoke(initial_state, config=config)
        except Exception as exc:
            import traceback
            elapsed = int((datetime.now(UTC) - start).total_seconds() * 1000)
            logger.error(
                "LangGraph run %s failed: %s\n%s",
                run_id, exc, traceback.format_exc(),
            )
            return AgentRunResult(
                status="failed",
                error_code=type(exc).__name__,
                error_message=str(exc)[:500],
                retryable=True,
                total_elapsed_ms=elapsed,
            )

        elapsed = int((datetime.now(UTC) - start).total_seconds() * 1000)
        return AgentRunResult(
            status="succeeded",
            public_response=result.get("public_response"),
            last_successful_node=result.get("next_node"),
            model_calls=result.get("model_calls", 0),
            node_hops=result.get("node_hops", 0),
            total_elapsed_ms=elapsed,
        )


class _StubRetriever:
    """B 成员未接入时的空检索器，返回空结果让链路可跑通。"""

    async def retrieve(self, *, query, filters, user_role):
        from dataclasses import dataclass, field

        @dataclass
        class _Empty:
            source_refs: list = field(default_factory=list)

        return _Empty()

