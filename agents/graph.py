"""
问答状态图（QA Mode）— V1.0

LangGraph 固定状态图，对应开发文档 6.3 节（图 4）。

节点流转:
  START → coordinator → knowledge → [sufficient?]
                          │             ├─ yes → evaluator_qa → END
                          │             └─ no  → refusal → END
                          └─ (error) → error_handler → END

依赖注入:
  - ModelGateway:    D 提供，类型为协议 agents.deps.ModelGateway
  - AgentEventSink:  D 提供，类型为协议 agents.deps.AgentEventSink
  - HybridRetriever: B 提供，类型为 c.schemas 中定义的检索接口

当前状态: 骨架代码，不含真实 LLM 调用。
          LLM 调用位使用 `# TODO: call ModelGateway` 标记。
          事件写入位使用 `# TODO: call AgentEventSink` 标记。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional, Protocol

from .state import AgentState, RetrievalFilters, SourceRef

# ═══════════════════════════════════════════════════════
# 依赖注入协议（C 定义接口，D / B 实现）
# ═══════════════════════════════════════════════════════


class ModelGateway(Protocol):
    """
    D 提供的模型调用接口。
    签名: invoke_structured(prompt, output_schema, agent_type, temperature) -> dict
    """

    async def invoke_structured(
        self,
        prompt: str,
        output_schema: dict,
        agent_type: Literal["coordinator", "knowledge", "questioner", "evaluator"],
        temperature: float = 0.0,
    ) -> dict:
        ...


class AgentEventSink(Protocol):
    """
    D 提供的事件写入接口。
    签名: emit(run_id, event_draft) -> None
    D 负责校验、写库、生成 sequence_no、发布 SSE。
    """

    async def emit(self, run_id: str, event_draft: dict) -> None:
        ...


class Retriever(Protocol):
    """
    B 提供的检索接口。
    签名: retrieve(query, query_embedding, filters, user_role) -> RetrievalResult
    """

    async def retrieve(
        self,
        query: str,
        query_embedding: Optional[list[float]] = None,
        filters: RetrievalFilters = None,
        user_role: Literal["member", "admin"] = "member",
    ) -> Any:  # -> RetrievalResult (from c.schemas)
        ...


# ═══════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════

MAX_MODEL_CALLS = 4
MAX_NODE_HOPS = 8
MAX_RETRIES = 2
MAX_EVIDENCE = 8
TEMPERATURE_KNOWLEDGE = 0.0
TEMPERATURE_COORDINATOR = 0.0
TEMPERATURE_EVALUATOR_QA = 0.2


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _limits_exceeded(state: AgentState) -> bool:
    return state.get("model_calls", 0) >= MAX_MODEL_CALLS or state.get("node_hops", 0) >= MAX_NODE_HOPS


def _build_event_draft(
    agent: str,
    event_type: str,
    status: str,
    summary: str,
    state: AgentState,
    duration_ms: float = 0,
    source_refs: Optional[list[SourceRef]] = None,
) -> dict:
    return {
        "id": f"evt-{uuid.uuid4().hex[:8]}",
        "run_id": state["run_id"],
        "agent": agent,
        "event_type": event_type,
        "status": status,
        "summary": summary,
        "source_refs": source_refs or [],
        "duration_ms": duration_ms,
        "created_at": _utc_now(),
    }


# ═══════════════════════════════════════════════════════
# 节点函数
# ═══════════════════════════════════════════════════════


async def coordinator_node(
    state: AgentState,
    model: ModelGateway,
    events: AgentEventSink,
) -> dict[str, Any]:
    """
    协调节点：意图识别 + 路由决策。

    路由结果:
      - "knowledge" → 进入知识检索
      - "refusal"   → 直接拒答（如明显不在课程范围的问题）
      - "error"     → 超过限额或其他异常
    """
    state["node_hops"] += 1

    if _limits_exceeded(state):
        return {
            "next_node": "error",
            "error": {"code": "AGENT_LIMIT_EXCEEDED", "message": "超过调用或节点上限", "retryable": False, "trace_id": state["run_id"]},
        }

    # TODO: 替换为 await model.invoke_structured(prompt, schema, "coordinator", TEMPERATURE_COORDINATOR)
    # 当前使用规则快速路由（开发文档 6.6：协调可由规则完成）
    decision = _rule_based_coordinator(state)

    await events.emit(state["run_id"], _build_event_draft(
        agent="coordinator",
        event_type="agent.summary",
        status="succeeded",
        summary=decision.get("public_summary", "协调 Agent 完成路由决策"),
        state=state,
    ))

    return {
        "next_node": decision.get("next_node", "knowledge"),
        "normalized_query": decision.get("normalized_query", state["user_input"]),
        "filters": decision.get("filters", state.get("filters", {})),
    }


def _rule_based_coordinator(state: AgentState) -> dict:
    """规则路由：当不需要 LLM 时直接决策，节省调用次数"""
    user_input = state.get("user_input", "")
    mode = state.get("mode", "qa")

    if mode == "qa":
        return {
            "intent": "qa_ask",
            "normalized_query": user_input.strip(),
            "next_node": "knowledge",
            "public_summary": "协调 Agent 识别为自由问答模式，路由至知识 Agent",
        }
    return {"intent": "other", "normalized_query": user_input.strip(), "next_node": "knowledge", "public_summary": "路由至知识 Agent"}


async def knowledge_node(
    state: AgentState,
    model: ModelGateway,
    events: AgentEventSink,
    retriever: Retriever,
) -> dict[str, Any]:
    """
    知识节点：检索 + 证据充分性判断。

    调用 B 的检索接口，返回最多 8 条 SourceRef，
    然后判断 sufficient 状态。
    """
    state["node_hops"] += 1

    if _limits_exceeded(state):
        return {"next_node": "error", "error": {"code": "AGENT_LIMIT_EXCEEDED", "message": "超过调用或节点上限", "retryable": False, "trace_id": state["run_id"]}}

    # Step 1: 调用 B 的检索
    filters = state.get("filters", {})
    retrieval_result = await retriever.retrieve(
        query=state.get("normalized_query", state.get("user_input", "")),
        filters=RetrievalFilters(
            chapter_ids=filters.get("chapter_ids", []),
            question_types=filters.get("question_types"),
            difficulty=filters.get("difficulty"),
            exclude_chunk_ids=filters.get("exclude_chunk_ids", []),
            knowledge_point_ids=filters.get("knowledge_point_ids", []),
            year=filters.get("year"),
        ) if filters else RetrievalFilters(),
        user_role="member",
    )

    evidence: list[SourceRef] = retrieval_result.source_refs[:MAX_EVIDENCE]
    sufficient: bool = retrieval_result.sufficient
    reason: str = retrieval_result.reason

    # Step 2: LLM 整理知识（需 Sufficient 时才调用模型）
    if sufficient:
        state["model_calls"] += 1
        # TODO: 替换为 await model.invoke_structured(prompt, schema, "knowledge", TEMPERATURE_KNOWLEDGE)
        # 当前跳过 LLM，直接传递 evidence 给 evaluator
        knowledge_items = [{"fact": ref["excerpt"], "source_ref_ids": [ref["document_id"]], "knowledge_point_ids": []} for ref in evidence]
        public_summary = f"知识 Agent 找到 {len(evidence)} 条可引用证据，判断证据充足"
    else:
        knowledge_items = []
        public_summary = f"知识 Agent 判断证据不足（{reason}）"

    await events.emit(state["run_id"], _build_event_draft(
        agent="knowledge",
        event_type="agent.summary",
        status="succeeded",
        summary=public_summary,
        state=state,
        source_refs=evidence,
    ))

    return {
        "evidence": evidence,
        "knowledge": knowledge_items,
        "sufficient": sufficient,
        "reason": reason,
        "next_node": "evaluator_qa" if sufficient else "refusal",
    }


async def evaluator_qa_node(
    state: AgentState,
    model: ModelGateway,
    events: AgentEventSink,
) -> dict[str, Any]:
    """
    评测讲解节点（问答模式）：组织答案 + 引用核验。

    约束：
    - 每个关键结论必须关联 evidence 中的 SourceRef
    - 不能创建新来源
    - 引用对应结论，不放末尾堆砌
    """
    state["node_hops"] += 1
    state["model_calls"] += 1

    if _limits_exceeded(state):
        return {"next_node": "error", "error": {"code": "AGENT_LIMIT_EXCEEDED", "message": "超过调用或节点上限", "retryable": False, "trace_id": state["run_id"]}}

    # TODO: 替换为 await model.invoke_structured(prompt, schema, "evaluator", TEMPERATURE_EVALUATOR_QA)
    # 当前使用规则模板生成回答
    evidence = state.get("evidence", [])
    knowledge = state.get("knowledge", [])

    # ── 引用核验 ──
    validated_citations = _validate_citations(knowledge, evidence)
    orphan_citations = [c for c in validated_citations if not c["has_source"]]
    if orphan_citations:
        # 引用不存在 → 阻止输出
        await events.emit(state["run_id"], _build_event_draft(
            agent="evaluator",
            event_type="agent.summary",
            status="failed",
            summary="引用核验失败——有结论无对应 SourceRef，阻止输出",
            state=state,
        ))
        return {
            "next_node": "error",
            "error": {"code": "AGENT_OUTPUT_INVALID", "message": "回答中包含无法核验的引用", "retryable": True, "trace_id": state["run_id"]},
        }

    # ── 构建回答（模板）──
    user_input = state.get("user_input", "")
    citations_md = "\n".join(
        f"- [{ref['document_name']} 第{ref['page_number']}页] {ref['excerpt'][:80]}..."
        for ref in evidence[:3]
    )
    answer = f"""**结论**
基于提供的课程资料，回答如下。

**依据与步骤**
{chr(10).join(k['fact'] for k in knowledge[:3])}

**来源**
{citations_md}

**提示**
以上内容基于指定课程资料。
"""

    await events.emit(state["run_id"], _build_event_draft(
        agent="evaluator",
        event_type="agent.summary",
        status="succeeded",
        summary=f"评测讲解 Agent 完成答案组织与引用核验，{len(evidence)} 条引用核验通过",
        state=state,
        source_refs=evidence,
    ))

    return {
        "public_response": answer,
        "next_node": "__end__",
    }


def _validate_citations(
    knowledge: list[dict],
    evidence: list[SourceRef],
) -> list[dict]:
    """核验每个 knowledge_item 的 source_ref_id 是否在 evidence 中"""
    valid_chunk_ids = {ref["chunk_id"] for ref in evidence}
    results = []
    for item in knowledge:
        ref_ids = item.get("source_ref_ids", [])
        has_source = any(rid in valid_chunk_ids for rid in ref_ids)
        results.append({"fact": item.get("fact", ""), "source_ref_ids": ref_ids, "has_source": has_source})
    return results


async def refusal_node(
    state: AgentState,
    events: AgentEventSink,
) -> dict[str, Any]:
    """
    拒答节点：生成结构化的拒答回应。

    参见 agents/prompts/refusal.py 的 7 种拒答模板。
    """
    from .prompts.refusal import RefusalTemplate

    reason = state.get("reason", "no_results")
    filters = state.get("filters", {})
    chapters = filters.get("chapter_ids", [])

    refusal = RefusalTemplate.build(
        reason=reason,
        searched_chapters=chapters if chapters else None,
    )

    public_response = (
        f"{refusal['conclusion']}\n\n"
        f"**检索范围**\n{refusal['searched_scope']}\n\n"
        f"**建议**\n{refusal['suggestion']}"
    )

    await events.emit(state["run_id"], _build_event_draft(
        agent="system",
        event_type="run.completed",
        status="succeeded",
        summary=f"已拒答——{reason}",
        state=state,
    ))

    return {
        "public_response": public_response,
        "next_node": "__end__",
    }


async def error_node(
    state: AgentState,
    events: AgentEventSink,
) -> dict[str, Any]:
    """失败节点：记录错误并终止运行"""
    error_info = state.get("error", {})
    if not error_info:
        error_info = {"code": "INTERNAL_ERROR", "message": "未知错误", "retryable": False, "trace_id": state["run_id"]}

    await events.emit(state["run_id"], _build_event_draft(
        agent="system",
        event_type="run.failed",
        status="failed",
        summary=f"运行失败——{error_info.get('code', 'UNKNOWN')}",
        state=state,
    ))

    return {
        "public_response": f"系统暂时无法完成：{error_info.get('message', '')}",
        "error": error_info,
        "next_node": "__end__",
    }


# ═══════════════════════════════════════════════════════
# 状态图构建器
# ═══════════════════════════════════════════════════════


def build_qa_graph():
    """
    构建问答状态图。

    依赖注入:
      - model:           D 的 ModelGateway 实例
      - events:          D 的 AgentEventSink 实例
      - retriever:       B 的 HybridRetriever 实例
      - checkpointer:    LangGraph PostgreSQL checkpointer

    用法:
      from langgraph.graph import StateGraph
      from agents.state import AgentState
      from agents.graph import build_qa_graph

      graph_builder = build_qa_graph()
      graph = graph_builder.compile(checkpointer=checkpointer)
      result = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": thread_id}})
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        raise ImportError("请安装 langgraph: pip install langgraph")

    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("knowledge", knowledge_node)
    builder.add_node("evaluator_qa", evaluator_qa_node)
    builder.add_node("refusal", refusal_node)
    builder.add_node("error", error_node)

    # 入口
    builder.set_entry_point("coordinator")

    # 边：节点间流转
    builder.add_conditional_edges(
        "coordinator",
        _route_from_coordinator,
        {"knowledge": "knowledge", "refusal": "refusal", "error": "error"},
    )

    builder.add_conditional_edges(
        "knowledge",
        _route_from_knowledge,
        {"evaluator_qa": "evaluator_qa", "refusal": "refusal", "error": "error"},
    )

    builder.add_edge("evaluator_qa", END)
    builder.add_edge("refusal", END)
    builder.add_edge("error", END)

    return builder


def _route_from_coordinator(state: AgentState) -> str:
    return state.get("next_node", "knowledge")


def _route_from_knowledge(state: AgentState) -> str:
    return state.get("next_node", "refusal")
