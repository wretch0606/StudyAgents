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

        # 依赖注入（使用 D 提供的 DB-backed retriever + DB session）
        from apps.api.db.session import _get_sessionmaker
        maker = _get_sessionmaker()
        async with maker() as db_session:
            config = {
                "configurable": {
                    "thread_id": f"thread-{_uuid.uuid4().hex[:16]}",
                    "model": model_gateway,
                    "event_sink": event_sink,
                    "retriever": _DbRetriever(),
                    "db_session": db_session,
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


class _DbRetriever:
    """从 knowledge_chunks 表直接检索的 DB 检索器。

    B 的 InMemory 后端无法跨进程共享（ingestion 在 Worker，QA 在 API）。
    因此 D 提供此 DB-backed 检索器作为过渡方案，查询 knowledge_chunks 表。
    """

    async def retrieve(self, *, query, filters, user_role):
        from dataclasses import dataclass, field

        from sqlalchemy import select as sa_select

        from apps.api.db.models.knowledge_chunk import KnowledgeChunk
        from apps.api.db.session import _get_sessionmaker

        @dataclass
        class _Result:
            source_refs: list = field(default_factory=list)

        @dataclass
        class _SourceRef:
            document_id: str
            document_name: str
            page_number: int
            chunk_id: str
            excerpt: str

        try:
            import logging
            _log = logging.getLogger(__name__)
            async with _get_sessionmaker()() as s:
                # 中文逐字拆分 + 英文空格分词
                import re
                raw_terms = re.split(r"[\s,，。！？、]+", query.strip())
                # 对每个词按单字拆分（中文）或保留（英文）
                all_terms = []
                for t in raw_terms:
                    if not t:
                        continue
                    if re.search(r"[一-鿿]", t):
                        # 中文：逐字 + 2-3字组合
                        all_terms.append(t)
                        for i in range(len(t)):
                            all_terms.append(t[i:i+1])
                            if i + 2 <= len(t):
                                all_terms.append(t[i:i+2])
                    else:
                        all_terms.append(t)
                # 去重，取前20个
                terms = list(dict.fromkeys(all_terms))[:20]
                stmt = sa_select(KnowledgeChunk)
                if terms:
                    from sqlalchemy import or_
                    conditions = [
                        KnowledgeChunk.content.ilike(f"%{t}%")
                        for t in terms
                    ]
                    stmt = stmt.where(or_(*conditions))
                stmt = stmt.limit(20)
                result = await s.execute(stmt)
                chunks = result.scalars().all()
                _log.info("_DbRetriever: query=%r terms=%d found=%d chunks",
                          query[:80], len(terms), len(chunks))

            refs = []
            for i, c in enumerate(chunks[:8]):
                refs.append(_SourceRef(
                    document_id=str(c.document_id),
                    document_name=f"doc-{str(c.document_id)[:8]}",
                    page_number=c.page_from,
                    chunk_id=str(c.id),
                    excerpt=c.content[:300],
                ))
            return _Result(source_refs=refs)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("_DbRetriever failed: %s", exc)
            return _Result(source_refs=[])
