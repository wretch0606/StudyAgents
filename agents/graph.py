"""
问答状态图（QA Mode）— V1.0

LangGraph 固定状态图，对应开发文档 6.3 节（图 4）。

节点流转:
  START → coordinator → knowledge → [sufficient?]
                          │             ├─ yes → evaluator_qa → END
                          │             └─ no  → refusal → END
                          └─ (error) → error → END

依赖（D / B 提供）:
  - ModelGateway:     from apps.api.services.model_gateway
  - AgentEventSink:   from apps.api.services.agent_event_sink (模块级单例)
  - AgentEventDraft:  from apps.api.schemas.agent
  - ModelMessage:     from apps.api.services.model_gateway
  - HybridRetriever:  from worker.retrieval.retriever (B 提供)
"""
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

try:
    from langchain_core.runnables import RunnableConfig
except ImportError:
    RunnableConfig = dict[str, Any]  # type: ignore[misc,assignment]

from .state import AgentState, SourceRef

try:
    from worker.schemas import (
        RetrievalFilters as WorkerRetrievalFilters,
    )
    from worker.schemas import (
        SourceRef as WorkerSourceRef,
    )
except ImportError:
    from apps.worker.schemas import (
        RetrievalFilters as WorkerRetrievalFilters,
    )
    from apps.worker.schemas import (
        SourceRef as WorkerSourceRef,
    )

# ── D 提供的接口 ─────────────────────────────────────
# 这些 import 路径来自 D 的接口文档
# (StudyAgents_ModelGateway与AgentEventSink接口说明.md)
# 当前 D 可能尚未提交对应代码，测试时使用 FakeAdapter
try:
    from apps.api.schemas.agent import AgentEventDraft
    from apps.api.services.agent_event_sink import agent_event_sink
    from apps.api.services.model_gateway import ModelGateway, ModelMessage
except ImportError:
    # D 的代码尚未合入时提供可运行的最小消息类型，便于独立测试 C。
    ModelGateway = Any  # type: ignore

    @dataclass(frozen=True)
    class ModelMessage:  # type: ignore[no-redef]
        role: str
        content: str

    @dataclass(frozen=True)
    class AgentEventDraft:  # type: ignore[no-redef]
        agent: str
        event_type: str
        status: str
        summary: str
        source_refs: list[SourceRef]
        duration_ms: int

    agent_event_sink = None

# ── C 的 Pydantic Schema ─────────────────────────────
# ── C 的提示词模板 ──────────────────────────────────
from .prompts.coordinator import SYSTEM_PROMPT as COORDINATOR_SYSTEM
from .prompts.coordinator import USER_MESSAGE_TEMPLATE as COORDINATOR_USER
from .prompts.evaluator import SYSTEM_PROMPT as EVALUATOR_SYSTEM
from .prompts.evaluator import USER_MESSAGE_TEMPLATE as EVALUATOR_USER
from .prompts.knowledge import SYSTEM_PROMPT as KNOWLEDGE_SYSTEM
from .prompts.knowledge import USER_MESSAGE_TEMPLATE as KNOWLEDGE_USER
from .schemas import (
    PROMPT_VERSIONS,
    CoordinatorDecision,
    KnowledgeResult,
    QAAnswer,
)

# ═══════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════

MAX_MODEL_CALLS = 4
MAX_NODE_HOPS = 8
MAX_EVIDENCE = 8


def _limits_exceeded(state: AgentState) -> bool:
    return (
        state.get("model_calls", 0) >= MAX_MODEL_CALLS
        or state.get("node_hops", 0) >= MAX_NODE_HOPS
    )


def _build_messages(system_prompt: str, user_message: str) -> list:
    """构建 D 的 ModelGateway 所需的 messages 列表"""
    return [
        ModelMessage(role="system", content=system_prompt),
        ModelMessage(role="user", content=user_message),
    ]


def _configurable(config: RunnableConfig | None) -> Mapping[str, Any]:
    """Return LangGraph configurable values without leaking them into state."""
    if config is None:
        return {}
    configurable = config.get("configurable", {})
    return configurable if isinstance(configurable, Mapping) else {}


def _require_dependency(
    config: RunnableConfig | None,
    name: str,
) -> Any:
    dependency = _configurable(config).get(name)
    if dependency is None:
        raise RuntimeError(f"LangGraph config.configurable 缺少依赖: {name}")
    return dependency


def _build_worker_filters(filters: Mapping[str, Any]) -> WorkerRetrievalFilters:
    """Adapt AgentState's JSON-friendly filter mapping to B's dataclass."""
    return WorkerRetrievalFilters(
        chapter_ids=list(filters.get("chapter_ids", [])),
        question_types=filters.get("question_types"),
        difficulty=filters.get("difficulty"),
        exclude_chunk_ids=list(filters.get("exclude_chunk_ids", [])),
        knowledge_point_ids=list(filters.get("knowledge_point_ids", [])),
        year=filters.get("year"),
    )


def _source_ref_to_state(ref: WorkerSourceRef | Mapping[str, Any]) -> SourceRef:
    """Normalize B's dataclass SourceRef into serializable LangGraph state."""
    if isinstance(ref, Mapping):
        data = dict(ref)
    elif is_dataclass(ref):
        data = asdict(ref)
    elif hasattr(ref, "model_dump"):
        data = ref.model_dump()
    else:
        data = {
            field: getattr(ref, field)
            for field in (
                "document_id",
                "document_name",
                "page_number",
                "question_no",
                "chunk_id",
                "excerpt",
                "page_image_url",
                "score",
            )
        }

    return SourceRef(
        document_id=str(data["document_id"]),
        document_name=str(data["document_name"]),
        page_number=int(data["page_number"]),
        question_no=data.get("question_no"),
        chunk_id=str(data["chunk_id"]),
        excerpt=str(data["excerpt"]),
        page_image_url=data.get("page_image_url"),
        score=float(data.get("score", 0.0)),
    )


# ═══════════════════════════════════════════════════════
# 节点函数
# ═══════════════════════════════════════════════════════


async def coordinator_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
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
            filters=state.get("filters", {}),
            next_node="knowledge",
            public_summary="协调 Agent 识别为自由问答模式，路由至知识 Agent",
        )
    else:
        model: ModelGateway = _require_dependency(config, "model")
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
        config=config,
    )

    return {
        "normalized_query": decision.normalized_query,
        "filters": decision.filters.model_dump() if hasattr(decision.filters, "model_dump") else {},
        "next_node": decision.next_node,
        "model_calls": state.get("model_calls", 0),
        "node_hops": state.get("node_hops", 0),
    }


async def knowledge_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    知识节点：检索 + 证据充分性判断。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    # Step 1: 调用 B 的检索接口
    model: ModelGateway = _require_dependency(config, "model")
    retriever = _require_dependency(config, "retriever")
    filters = state.get("filters", {})
    retrieval_result = await retriever.retrieve(
        query=state.get("normalized_query", state.get("user_input", "")),
        filters=_build_worker_filters(filters),
        user_role="member",
    )

    evidence: list[SourceRef] = [
        _source_ref_to_state(ref)
        for ref in retrieval_result.source_refs[:MAX_EVIDENCE]
    ]

    # 构建 REF 标签映射（REF_1 → 真实 chunk_id）
    ref_map: dict[str, str] = {}
    evidence_lines: list[str] = []
    for i, ref in enumerate(evidence):
        label = f"REF_{i + 1}"
        ref_map[label] = ref["chunk_id"]
        evidence_lines.append(
            f"[{label}] {ref['document_name']} 第{ref['page_number']}页: {ref['excerpt']}"
        )
    evidence_text = "\n---\n".join(evidence_lines) if evidence_lines else "（无检索结果）"

    # Step 2: LLM 整理知识
    state["model_calls"] = state.get("model_calls", 0) + 1

    # 注入 REF 标签规则到 system prompt
    ref_rule = (
        "\n## 引用规则（严格遵守）\n"
        "只能使用以下 REF 标签格式引用证据："
        + ", ".join(ref_map.keys())
        + "\n"
        "禁止使用 document_id、URL 或自造标识符。\n"
        "source_ref_ids 必须填写 REF 标签，如 [\"REF_1\", \"REF_3\"]。\n"
        "selected_source_ref_ids 同理。"
    )
    sys_prompt = KNOWLEDGE_SYSTEM + ref_rule

    user_msg = KNOWLEDGE_USER.format(
        normalized_query=state.get("normalized_query", state.get("user_input", "")),
        evidence_text=evidence_text,
        filters=filters,
        user_role="member",
    )
    messages = _build_messages(sys_prompt, user_msg)

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

    # 将 REF 标签映射回真实 chunk_id
    for item in kr.knowledge_items:
        mapped_ids = []
        for rid in item.source_ref_ids:
            mapped_ids.append(ref_map.get(rid, rid))
        item.source_ref_ids = mapped_ids
    mapped_selected = []
    for rid in kr.selected_source_ref_ids:
        mapped_selected.append(ref_map.get(rid, rid))
    kr.selected_source_ref_ids = mapped_selected

    # 发布事件
    sufficiency_label = "充足" if kr.sufficient else "不足"
    summary = (
        f"知识 Agent 找到 {len(evidence)} 条可引用证据，"
        f"判断证据{sufficiency_label}（{kr.reason}）"
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
        config=config,
    )

    return {
        "evidence": evidence,
        "knowledge": [k.model_dump() for k in kr.knowledge_items],
        "sufficient": kr.sufficient,
        "reason": kr.reason,
        "next_node": "evaluator_qa" if kr.sufficient else "refusal",
        "model_calls": state.get("model_calls", 0),
        "node_hops": state.get("node_hops", 0),
    }


async def evaluator_qa_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    评测讲解节点（问答模式）：组织答案 + 引用核验。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1
    state["model_calls"] = state.get("model_calls", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    model: ModelGateway = _require_dependency(config, "model")
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
                config=config,
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

    # 【Day6 修复】引用准确率：检查 answer 中是否包含 citation 标记
    import re as _re
    _citation_in_text = _re.findall(r'\[.+?第\d+页\]', answer.answer)
    _has_citations = len(_citation_in_text) >= 1
    if not _has_citations and evidence:
        import logging as _logging
        _logging.getLogger(__name__).warning("回答中缺少引用标记，重试一次")
        _retry_msg = EVALUATOR_USER.format(
            user_input=state.get("user_input", "") + "\n\n【重要提醒】在回答的每句话后面标注引用，格式：[文档名 第X页]。不要只在末尾列来源。",
            knowledge_text=knowledge_text,
            source_refs_text=source_refs_text,
        )
        _retry_msgs = _build_messages(EVALUATOR_SYSTEM, _retry_msg)
        result = await model.invoke_structured(
            run_id=state["run_id"],
            trace_id=state.get("trace_id", state["run_id"]),
            agent="evaluator",
            prompt_version=PROMPT_VERSIONS["evaluator"],
            messages=_retry_msgs,
            output_schema=QAAnswer,
            temperature=0.1,
        )
        answer = result.output
        state["model_calls"] = state.get("model_calls", 0) + 1

    await _emit(
        state=state,
        agent="evaluator",
        event_type="agent.summary",
        status="succeeded",
        summary=answer.public_summary,
        source_refs=evidence,
        config=config,
    )

    return {
        "public_response": answer.answer,
        "next_node": "__end__",
        "model_calls": state.get("model_calls", 0),
        "node_hops": state.get("node_hops", 0),
    }


async def refusal_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """拒答节点：生成结构化拒答回应"""
    from .prompts.refusal import RefusalTemplate

    state["node_hops"] = state.get("node_hops", 0) + 1
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
        config=config,
    )

    return {
        "public_response": public_response,
        "next_node": "__end__",
        "model_calls": state.get("model_calls", 0),
        "node_hops": state.get("node_hops", 0),
    }


async def error_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """失败节点"""
    state["node_hops"] = state.get("node_hops", 0) + 1
    error_info = state.get("error", {})
    await _emit(
        state=state,
        agent="system",
        event_type="run.failed",
        status="failed",
        summary=f"运行失败——{error_info.get('code', 'UNKNOWN')}",
        config=config,
    )
    return {
        "public_response": f"系统暂时无法完成：{error_info.get('message', '')}",
        "next_node": "__end__",
        "model_calls": state.get("model_calls", 0),
        "node_hops": state.get("node_hops", 0),
    }


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════


def _error_return(state: AgentState, code: str, message: str, retryable: bool) -> dict:
    return {
        "next_node": "error",
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "trace_id": state.get("trace_id", state["run_id"]),
        },
        "model_calls": state.get("model_calls", 0),
        "node_hops": state.get("node_hops", 0),
    }


async def _emit(
    state: AgentState,
    agent: str,
    event_type: str,
    status: str,
    summary: str,
    source_refs: list[SourceRef] | None = None,
    config: RunnableConfig | None = None,
):
    """通过 D 的 AgentEventSink 发布公开事件"""
    configurable = _configurable(config)
    sink = configurable.get("event_sink", agent_event_sink)
    if sink is None:
        return  # D 的代码尚未合入，静默跳过

    # 将内部 TypedDict SourceRef 映射为 Pydantic SourceRef（去除不被 schema 接受的字段）
    allowed_ref_keys = {
        "chunk_id",
        "document_id",
        "document_name",
        "excerpt",
        "page_image_url",
        "page_no",
        "question_no",
    }
    mapped_refs = []
    for ref in (source_refs or []):
        if isinstance(ref, dict):
            mapped = {}
            for k, v in ref.items():
                if k == "page_number":
                    mapped["page_no"] = v
                elif k in allowed_ref_keys:
                    mapped[k] = v
            if "page_no" not in mapped and "page_number" not in ref:
                pass  # keep as-is if no page field
            mapped_refs.append(mapped)
        else:
            # dataclass or object: filter allowed attributes
            mapped = {}
            for k in allowed_ref_keys:
                if hasattr(ref, k):
                    mapped[k] = getattr(ref, k)
            if hasattr(ref, "page_number") and "page_no" not in mapped:
                mapped["page_no"] = getattr(ref, "page_number")
            mapped_refs.append(mapped)

    draft = AgentEventDraft(
        agent=agent,
        event_type=event_type,
        status=status,
        summary=summary,
        source_refs=mapped_refs,
        duration_ms=0,
    )
    db = configurable.get("db_session")
    if db is not None:
        await sink.emit(
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

    依赖注入（由各节点从 LangGraph config["configurable"] 读取）:
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
