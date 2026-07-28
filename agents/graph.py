"""
问答状态图（QA Mode）— V1.0

LangGraph 固定状态图，对应开发文档 6.3 节（图 4）。

节点流转:
  START → coordinator → knowledge → [sufficient?]
                          │             ├─ yes → evaluator_qa → END
                          │             └─ no  → refusal → END
                          └─ (error) → error_handler → END

依赖（D / B 提供）:
  - ModelGateway:     from apps.api.services.model_gateway
  - AgentEventSink:   from apps.api.services.agent_event_sink (模块级单例)
  - AgentEventDraft:  from apps.api.schemas.agent
  - ModelMessage:     from apps.api.services.model_gateway
  - HybridRetriever:  from worker.retrieval.retriever (B 提供)
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from .state import AgentState, RetrievalFilters, SourceRef

# ── D 提供的接口 ─────────────────────────────────────
# 这些 import 路径来自 D 的接口文档
# (StudyAgents_ModelGateway与AgentEventSink接口说明.md)
# 当前 D 可能尚未提交对应代码，测试时使用 FakeAdapter
try:
    from apps.api.schemas.agent import AgentEventDraft
    from apps.api.services.agent_event_sink import agent_event_sink
    from apps.api.services.model_gateway import ModelGateway, ModelMessage
except ImportError:
    # D 的代码尚未合入时降级为 Protocol + 占位
    ModelGateway = object  # type: ignore
    ModelMessage = object  # type: ignore
    AgentEventDraft = object  # type: ignore
    agent_event_sink = None

# ── C 的 Pydantic Schema ─────────────────────────────
from .schemas import (
    PROMPT_VERSIONS,
    CoordinatorDecision,
    KnowledgeResult,
    QAAnswer,
)

# ── C 的提示词模板 ──────────────────────────────────
from .prompts.coordinator import SYSTEM_PROMPT as COORDINATOR_SYSTEM
from .prompts.coordinator import USER_MESSAGE_TEMPLATE as COORDINATOR_USER
from .prompts.knowledge import SYSTEM_PROMPT as KNOWLEDGE_SYSTEM
from .prompts.knowledge import USER_MESSAGE_TEMPLATE as KNOWLEDGE_USER
from .prompts.evaluator import SYSTEM_PROMPT as EVALUATOR_SYSTEM
from .prompts.evaluator import USER_MESSAGE_TEMPLATE as EVALUATOR_USER

# ═══════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════

MAX_MODEL_CALLS = 4
MAX_NODE_HOPS = 8
MAX_EVIDENCE = 8


def _limits_exceeded(state: AgentState) -> bool:
    return state.get("model_calls", 0) >= MAX_MODEL_CALLS or state.get("node_hops", 0) >= MAX_NODE_HOPS


def _build_messages(system_prompt: str, user_message: str) -> list:
    """构建 D 的 ModelGateway 所需的 messages 列表"""
    return [
        ModelMessage(role="system", content=system_prompt),
        ModelMessage(role="user", content=user_message),
    ]


# ═══════════════════════════════════════════════════════
# 节点函数
# ═══════════════════════════════════════════════════════


async def coordinator_node(state: AgentState, model: ModelGateway) -> dict[str, Any]:
    """
    协调节点：意图识别 + 路由决策。

    优先使用规则快速路由（省一次 LLM 调用），
    复杂意图时调用 model.invoke_structured()。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    mode = state.get("mode", "qa")
    user_input = state.get("user_input", "")

    # 规则路由：qa 模式下直接走知识检索，节省模型调用
    if mode == "qa":
        decision = CoordinatorDecision(
            intent="qa_ask",
            normalized_query=user_input.strip(),
            next_node="knowledge",
            public_summary="协调 Agent 识别为自由问答模式，路由至知识 Agent",
        )
    else:
        state["model_calls"] = state.get("model_calls", 0) + 1
        user_msg = COORDINATOR_USER.format(
            mode=mode,
            user_input=user_input,
            filters=state.get("filters", {}),
            model_calls=state.get("model_calls", 0),
            node_hops=state.get("node_hops", 0),
        )
        messages = _build_messages(COORDINATOR_SYSTEM, user_msg)

        result = await model.invoke_structured(
            run_id=state["run_id"],
            trace_id=state.get("trace_id", state["run_id"]),
            agent="coordinator",
            prompt_version=PROMPT_VERSIONS["coordinator"],
            messages=messages,
            output_schema=CoordinatorDecision,
        )
        decision = result.output

    # 发布事件
    await _emit(
        state=state,
        agent="coordinator",
        event_type="agent.summary",
        status="succeeded",
        summary=decision.public_summary,
    )

    return {
        "normalized_query": decision.normalized_query,
        "filters": decision.filters.model_dump() if hasattr(decision.filters, "model_dump") else {},
        "next_node": decision.next_node,
    }


async def knowledge_node(
    state: AgentState,
    model: ModelGateway,
    retriever: Any,  # B 的 HybridRetriever
) -> dict[str, Any]:
    """
    知识节点：检索 + 证据充分性判断。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    # Step 1: 调用 B 的检索接口
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

    # Step 2: LLM 整理知识
    state["model_calls"] = state.get("model_calls", 0) + 1

    # 将 evidence 格式化为文本（给模型阅读）
    evidence_text = "\n---\n".join(
        f"[{i+1}] {ref['document_name']} 第{ref['page_number']}页: {ref['excerpt']}"
        for i, ref in enumerate(evidence)
    ) if evidence else "（无检索结果）"

    user_msg = KNOWLEDGE_USER.format(
        normalized_query=state.get("normalized_query", state.get("user_input", "")),
        evidence_text=evidence_text,
        filters=filters,
        user_role="member",
    )
    messages = _build_messages(KNOWLEDGE_SYSTEM, user_msg)

    result = await model.invoke_structured(
        run_id=state["run_id"],
        trace_id=state.get("trace_id", state["run_id"]),
        agent="knowledge",
        prompt_version=PROMPT_VERSIONS["knowledge"],
        messages=messages,
        output_schema=KnowledgeResult,
        temperature=0.0,
    )
    kr: KnowledgeResult = result.output

    # 发布事件
    summary = (
        f"知识 Agent 找到 {len(evidence)} 条可引用证据，判断证据{'充足' if kr.sufficient else '不足'}（{kr.reason}）"
        if evidence
        else f"知识 Agent 未找到匹配证据（{kr.reason}）"
    )
    await _emit(
        state=state,
        agent="knowledge",
        event_type="agent.summary",
        status="succeeded",
        summary=summary,
        source_refs=evidence if kr.sufficient else [],
    )

    return {
        "evidence": evidence,
        "knowledge": [k.model_dump() for k in kr.knowledge_items],
        "sufficient": kr.sufficient,
        "reason": kr.reason,
        "next_node": "evaluator_qa" if kr.sufficient else "refusal",
    }


async def evaluator_qa_node(state: AgentState, model: ModelGateway) -> dict[str, Any]:
    """
    评测讲解节点（问答模式）：组织答案 + 引用核验。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1
    state["model_calls"] = state.get("model_calls", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    evidence = state.get("evidence", [])
    knowledge = state.get("knowledge", [])

    # ── 引用核验（规则，不依赖 LLM）──
    valid_chunk_ids = {ref["chunk_id"] for ref in evidence}
    for item in knowledge:
        ref_ids = item.get("source_ref_ids", [])
        if not any(rid in valid_chunk_ids for rid in ref_ids):
            await _emit(
                state=state,
                agent="evaluator",
                event_type="agent.summary",
                status="failed",
                summary="引用核验失败——有结论无对应 SourceRef，阻止输出",
            )
            return _error_return(state, "AGENT_OUTPUT_INVALID", "回答中包含无法核验的引用", True)

    # ── LLM 组织回答 ──
    knowledge_text = "\n".join(
        f"- {item['fact']} [来源: {', '.join(item.get('source_ref_ids', []))}]"
        for item in knowledge
    )
    source_refs_text = "\n".join(
        f"[{ref['document_name']} 第{ref['page_number']}页] {ref['excerpt'][:100]}..."
        for ref in evidence
    )

    user_msg = EVALUATOR_USER.format(
        user_input=state.get("user_input", ""),
        knowledge_text=knowledge_text,
        source_refs_text=source_refs_text,
    )
    messages = _build_messages(EVALUATOR_SYSTEM, user_msg)

    result = await model.invoke_structured(
        run_id=state["run_id"],
        trace_id=state.get("trace_id", state["run_id"]),
        agent="evaluator",
        prompt_version=PROMPT_VERSIONS["evaluator"],
        messages=messages,
        output_schema=QAAnswer,
        temperature=0.2,
    )
    answer: QAAnswer = result.output

    await _emit(
        state=state,
        agent="evaluator",
        event_type="agent.summary",
        status="succeeded",
        summary=answer.public_summary,
        source_refs=evidence,
    )

    return {
        "public_response": answer.answer,
        "next_node": "__end__",
    }


async def refusal_node(state: AgentState) -> dict[str, Any]:
    """拒答节点：生成结构化拒答回应"""
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

    await _emit(
        state=state,
        agent="system",
        event_type="run.completed",
        status="succeeded",
        summary=f"已拒答——{reason}",
    )

    return {
        "public_response": public_response,
        "next_node": "__end__",
    }


async def error_node(state: AgentState) -> dict[str, Any]:
    """失败节点"""
    error_info = state.get("error", {})
    await _emit(
        state=state,
        agent="system",
        event_type="run.failed",
        status="failed",
        summary=f"运行失败——{error_info.get('code', 'UNKNOWN')}",
    )
    return {
        "public_response": f"系统暂时无法完成：{error_info.get('message', '')}",
        "next_node": "__end__",
    }


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════


def _error_return(state: AgentState, code: str, message: str, retryable: bool) -> dict:
    return {
        "next_node": "error",
        "error": {"code": code, "message": message, "retryable": retryable, "trace_id": state.get("trace_id", state["run_id"])},
    }


async def _emit(
    state: AgentState,
    agent: str,
    event_type: str,
    status: str,
    summary: str,
    source_refs: Optional[list[SourceRef]] = None,
):
    """通过 D 的 AgentEventSink 发布公开事件"""
    if agent_event_sink is None:
        return  # D 的代码尚未合入，静默跳过

    draft = AgentEventDraft(
        agent=agent,
        event_type=event_type,
        status=status,
        summary=summary,
        source_refs=source_refs or [],
        duration_ms=0,
    )
    # db_session 需通过 LangGraph config["configurable"]["db_session"] 传入
    # 当前通过 state 传递引用，实际调用时由外层注入
    db = state.get("_db_session")  # type: ignore
    if db is not None:
        await agent_event_sink.emit(
            run_id=state["run_id"],
            event=draft,
            db_session=db,
        )


# ═══════════════════════════════════════════════════════
# 状态图构建器
# ═══════════════════════════════════════════════════════


def build_qa_graph():
    """
    构建问答状态图。

    依赖注入（通过 LangGraph config["configurable"] 传入）:
      - model:      D 的 ModelGateway 实例
      - retriever:  B 的 HybridRetriever 实例
      - db_session: SQLAlchemy AsyncSession

    用法:
      from langgraph.graph import StateGraph
      from agents.state import AgentState
      from agents.graph import build_qa_graph

      graph = build_qa_graph().compile(checkpointer=checkpointer)
      result = await graph.ainvoke(
          initial_state,
          config={
              "configurable": {
                  "thread_id": thread_id,
                  "model": model_instance,
                  "retriever": retriever_instance,
                  "db_session": db_session,
              }
          }
      )
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        raise ImportError("请安装 langgraph: pip install langgraph")

    builder = StateGraph(AgentState)

    builder.add_node("coordinator", coordinator_node)
    builder.add_node("knowledge", knowledge_node)
    builder.add_node("evaluator_qa", evaluator_qa_node)
    builder.add_node("refusal", refusal_node)
    builder.add_node("error", error_node)

    builder.set_entry_point("coordinator")

    builder.add_conditional_edges("coordinator", _route, {
        "knowledge": "knowledge",
        "refusal": "refusal",
        "error": "error",
    })
    builder.add_conditional_edges("knowledge", _route, {
        "evaluator_qa": "evaluator_qa",
        "refusal": "refusal",
        "error": "error",
    })

    builder.add_edge("evaluator_qa", END)
    builder.add_edge("refusal", END)
    builder.add_edge("error", END)

    return builder


def _route(state: AgentState) -> str:
    return state.get("next_node", "error")
