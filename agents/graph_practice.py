"""
训练状态图（Practice Mode）— V1.1

LangGraph 固定状态图，对应开发文档 6.4 节（图 5）。

节点流转:
  START → coordinator → questioner → [WaitForAnswer via interrupt]
                                           │
                                           ▼
                                        evaluator → [more?]
                                           │           ├─ yes → questioner
                                           │           └─ no  → summary → END

Day 6 修复（V1.1）：
  - 节点签名统一为 (state, config)，从 config 读取 model/retriever
  - 对齐 QA 图的依赖注入模式

依赖（D / B 提供）:
  - ModelGateway:     通过 config["configurable"]["model"]
  - AgentEventSink:   通过 config["configurable"]["event_sink"]
  - HybridRetriever:  通过 config["configurable"]["retriever"]
  - LangGraph interrupt:  D 的 PostgreSQL checkpointer
"""
# 注意：不使用 from __future__ import annotations，
# LangGraph 需要运行时解析 config 参数的类型标注来识别 RunnableConfig。

import uuid
from typing import Any, Optional

try:
    from langchain_core.runnables import RunnableConfig
except ImportError:
    RunnableConfig = dict[str, Any]  # type: ignore[misc,assignment]

from .state import AgentState, SourceRef

# ── D/B 接口（同 graph.py）──
try:
    from apps.api.schemas.agent import AgentEventDraft
    from apps.api.services.agent_event_sink import agent_event_sink
    from apps.api.services.model_gateway import ModelGateway, ModelMessage
except ImportError:
    ModelGateway = object  # type: ignore
    ModelMessage = object  # type: ignore
    AgentEventDraft = object  # type: ignore
    agent_event_sink = None

from .graph import (
    _build_messages,
    _emit,
    _error_return,
    _limits_exceeded,
    _require_dependency,
    _build_worker_filters,
    MAX_EVIDENCE,
    MAX_MODEL_CALLS,
    MAX_NODE_HOPS,
)
from .schemas import (
    PROMPT_VERSIONS,
    GeneratedQuestionPrivate,
    GradeResultPrivate,
    PracticeFeedback,
    StepFeedbackPublic,
)
from .rules.grading import (
    grade_choice,
    grade_fill_blank,
    validate_step_scores,
)

# ── 提示词 ──
from .prompts.questioner import (
    SYSTEM_PROMPT as QUESTIONER_SYSTEM,
    USER_MESSAGE_TEMPLATE as QUESTIONER_USER,
)
from .prompts.evaluator import (
    SYSTEM_PROMPT as EVALUATOR_SYSTEM,
    USER_MESSAGE_TEMPLATE as EVALUATOR_USER,
)

# ── 公共错误节点（从 QA 图复用）──
from .graph import error_node as _qa_error_node

# ═══════════════════════════════════════════════════════
# 节点函数
# ═══════════════════════════════════════════════════════


async def coordinator_practice_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """
    协调节点（训练模式）：解析用户选择的章节/题型/难度/题数。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    filters = state.get("filters", {})
    target_count = filters.get("target_count", 5) if isinstance(filters, dict) else 5

    await _emit(
        state=state,
        agent="coordinator",
        event_type="agent.summary",
        status="succeeded",
        summary=(
            f"协调 Agent 开始专项训练：{filters.get('chapter_ids', ['全部'])}章节，"
            f"{filters.get('question_types', ['全部'])}题型，"
            f"难度{filters.get('difficulty', 2)}，共{target_count}题"
        ),
        config=config,
    )

    return {
        "next_node": "questioner",
        "target_count": target_count,
        "current_item_index": 0,
        "practice_items": [],
        "exclude_chunk_ids": [],
        "practice_scores": [],
    }


async def questioner_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """
    出题节点：真题优先 → 变式生成。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1
    state["model_calls"] = state.get("model_calls", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    model: ModelGateway = _require_dependency(config, "model")
    retriever = _require_dependency(config, "retriever")
    filters = state.get("filters", {})
    exclude_ids = state.get("exclude_chunk_ids", [])

    # Step 1: 以 admin 身份检索真题候选（获取含答案的块）
    worker_filters = _build_worker_filters(filters)
    worker_filters.exclude_chunk_ids = list(exclude_ids) if exclude_ids else []
    exam_result = await retriever.retrieve(
        query="",
        filters=worker_filters,
        user_role="admin",  # admin 可获取含答案的私有块
    )

    exam_candidates = exam_result.source_refs[:MAX_EVIDENCE] if hasattr(exam_result, "source_refs") else []

    # Step 2: LLM 出题
    question_types = filters.get("question_types", ["calculation"]) if isinstance(filters, dict) else ["calculation"]
    user_msg = QUESTIONER_USER.format(
        knowledge_points=filters.get("knowledge_point_ids", ["全部"]) if isinstance(filters, dict) else ["全部"],
        difficulty=filters.get("difficulty", 2) if isinstance(filters, dict) else 2,
        question_type=question_types[0] if question_types else "calculation",
        exam_candidates_text=_format_refs(exam_candidates),
        evidence_text=_format_refs(exam_candidates),
        used_count=state.get("current_item_index", 0),
        total_count=state.get("target_count", 5),
        exclude_chunk_ids=exclude_ids,
    )
    messages = _build_messages(QUESTIONER_SYSTEM, user_msg)

    result = await model.invoke_structured(
        run_id=state["run_id"],
        trace_id=state.get("trace_id", state["run_id"]),
        agent="questioner",
        prompt_version=PROMPT_VERSIONS["questioner"],
        messages=messages,
        output_schema=GeneratedQuestionPrivate,
        temperature=0.4,
    )
    question: GeneratedQuestionPrivate = result.output

    # Step 3: 置信度检查
    if question.confidence < 0.8:
        await _emit(
            state=state, agent="questioner", event_type="agent.summary",
            status="succeeded",
            summary=f"出题 Agent 生成题目置信度 {question.confidence:.2f} < 0.8，降级使用真题",
            config=config,
        )

    # Step 4: 构造公开题目和私有数据
    item_id = question.question_id or str(uuid.uuid4())
    # current_item_index 保持 0-based，order_no 用于展示（1-based）
    idx = state.get("current_item_index", 0)
    order_no = idx + 1

    public_item = {
        "item_id": item_id,
        "order_no": order_no,
        "source_kind": question.source_kind,
        "question_type": question.question_type,
        "difficulty": question.difficulty,
        "stem": question.stem,
        "options": question.options,
        "source_label": _build_source_label(question),
        "progress": {"current": order_no, "total": state.get("target_count", 5)},
    }

    practice_items = list(state.get("practice_items", []))
    practice_items.append({
        "item_id": item_id,
        "order_no": order_no,
        "public": public_item,
        "private": question.private.model_dump(),
        "source_refs": question.source_refs,
        "source_kind": question.source_kind,
        "question_type": question.question_type,
        "difficulty": question.difficulty,
    })

    await _emit(
        state=state,
        agent="questioner",
        event_type="agent.summary",
        status="succeeded",
        summary=question.public_summary,
        config=config,
    )

    return {
        "practice_items": practice_items,
        "practice_items_count": len(practice_items),
        "current_public_question": public_item,
        "next_node": "wait_for_answer",
    }


async def wait_for_answer_node(state: AgentState) -> dict[str, Any]:
    """
    等待用户提交答案。使用 LangGraph interrupt 暂停。

    D 需配置 checkpointer 以支持 interrupt。
    """
    from langgraph.types import interrupt

    user_answer = interrupt("waiting_for_answer")
    state["user_answer"] = user_answer

    return {
        "user_answer": user_answer,
        "next_node": "evaluator",
    }


async def evaluator_practice_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """
    评测节点（训练模式）：客观题规则评分 / 主观题 LLM 评分。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    practice_items = state.get("practice_items", [])
    idx = state.get("current_item_index", 0)  # 0-based，questioner 不再覆写
    if idx < 0 or idx >= len(practice_items):
        return _error_return(state, "PRACTICE_STATE_CONFLICT", "题目索引越界", True)

    current = practice_items[idx]
    user_answer = state.get("user_answer", "")
    private = current["private"]
    question_type = current["question_type"]

    # ── 客观题：规则评分，不调 LLM ──
    if question_type in ("choice", "fill_blank"):
        rubric = private.get("rubric", [])
        # 从评分规则中计算满分（至少 1 分，确保非零）
        max_score = sum(r["max_score"] for r in rubric) if rubric else 1

        if question_type == "choice":
            grade = grade_choice(user_answer, private["expected_answer"], max_score)
        else:
            acceptable = rubric[0].get("acceptable_forms", []) if rubric else None
            grade = grade_fill_blank(user_answer, private["expected_answer"], acceptable, max_score)

        feedback = _build_feedback(
            grade["score"], max_score,
            [{"status": "met" if grade["met"] else "not_met", "text": grade["feedback"]}],
            "", grade["confidence"], False,
        )
        return _finish_item(state, current, feedback, grade)

    # ── 主观题：LLM 评分 ──
    model: ModelGateway = _require_dependency(config, "model")
    state["model_calls"] = state.get("model_calls", 0) + 1

    rubric_text = "\n".join(
        f"{r['id']}: {r['description']} (满分 {r['max_score']}分)"
        for r in private.get("rubric", [])
    )
    user_msg = EVALUATOR_USER.format(
        user_input=current.get("public", {}).get("stem", ""),
        knowledge_text=f"标准答案: {private['expected_answer']}\n评分规则:\n{rubric_text}",
        source_refs_text=_format_refs(current.get("source_refs", [])),
    )
    messages = _build_messages(EVALUATOR_SYSTEM, user_msg)

    result = await model.invoke_structured(
        run_id=state["run_id"],
        trace_id=state.get("trace_id", state["run_id"]),
        agent="evaluator",
        prompt_version=PROMPT_VERSIONS["evaluator_practice"],
        messages=messages,
        output_schema=GradeResultPrivate,
        temperature=0.0,
    )
    grade_result: GradeResultPrivate = result.output

    # ── 校验：分步得分不超上限 ──
    rubric = private.get("rubric", [])
    max_total = sum(r["max_score"] for r in rubric)
    validation = validate_step_scores(
        [s.model_dump() for s in grade_result.step_scores],
        rubric,
        max_total,
    )
    if not validation["valid"]:
        await _emit(
            state=state, agent="evaluator", event_type="agent.summary",
            status="failed",
            summary=f"评分校验失败: {validation['violations']}",
            config=config,
        )

    final_score = validation["total"]
    review_required = grade_result.confidence < 0.7 or grade_result.review_required

    # ── 构建公开反馈（剥离私有评分点 ID）──
    public_steps = [
        StepFeedbackPublic(status=s.status, text=s.feedback).model_dump()
        for s in grade_result.step_scores
    ]
    feedback = PracticeFeedback(
        score=final_score,
        max_score=max_total,
        score_ratio=final_score / max_total if max_total > 0 else 0,
        verdict=_verdict_label(final_score / max_total if max_total > 0 else 0),
        steps=[StepFeedbackPublic(**s) for s in public_steps],
        explanation=grade_result.explanation,
        confidence=grade_result.confidence,
        review_required=review_required,
    )

    await _emit(
        state=state,
        agent="evaluator",
        event_type="agent.summary",
        status="succeeded",
        summary=grade_result.public_summary,
        config=config,
    )

    return _finish_item(
        state, current,
        feedback.model_dump(),
        {"score": final_score, "max_score": max_total, "confidence": grade_result.confidence},
    )


def _finish_item(state: AgentState, current: dict, feedback: dict, grade: dict) -> dict:
    """记录本题评分，决定下一题还是结束"""
    practice_items = state.get("practice_items", [])
    idx = state.get("current_item_index", 0)  # 0-based
    if idx < len(practice_items):
        practice_items[idx]["feedback"] = feedback
        practice_items[idx]["grade"] = grade

    current_idx = idx  # 0-based
    target = state.get("target_count", 5)
    scores = state.get("practice_scores", [])
    grade_ratio = grade.get("score_ratio", grade.get("score", 0) / max(grade.get("max_score", 1), 1))
    scores = list(scores) + [grade_ratio]

    if current_idx + 1 >= target:
        # 最后一题 → 生成总结
        total_score = sum(
            it.get("grade", {}).get("score", 0)
            for it in practice_items
        )
        total_max = sum(
            it.get("grade", {}).get("max_score", 0)
            for it in practice_items
        )
        summary = {
            "total_score": total_score,
            "total_max": total_max,
            "total_ratio": total_score / total_max if total_max > 0 else 0,
            "items_count": len(practice_items),
            "mastery_updates": [],
        }
        return {
            "practice_items": practice_items,
            "current_feedback": feedback,
            "practice_summary": summary,
            "next_node": "summary",
        }
    else:
        # 继续下一题（current_item_index + 1 = 下一个 0-based 索引）
        exclude_ids = list(state.get("exclude_chunk_ids", []))
        for c in current.get("source_refs", []):
            cid = c.get("chunk_id", "") if isinstance(c, dict) else getattr(c, "chunk_id", "")
            if cid:
                exclude_ids.append(cid)
        return {
            "practice_items": practice_items,
            "current_feedback": feedback,
            "current_item_index": current_idx + 1,
            "exclude_chunk_ids": exclude_ids,
            "next_node": "questioner",
        }


async def summary_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """训练结束：输出总结"""
    s = state.get("practice_summary", {})
    public_response = (
        f"**训练完成**\n\n"
        f"总分：{s.get('total_score', 0)} / {s.get('total_max', 0)} "
        f"（{s.get('total_ratio', 0) * 100:.0f}%）\n"
        f"题目数：{s.get('items_count', 0)}\n\n"
        f"错题已自动加入错题本，可随时复习。"
    )
    await _emit(
        state=state, agent="system", event_type="run.completed",
        status="succeeded", summary="训练完成", config=config,
    )
    return {"public_response": public_response, "next_node": "__end__"}


# ═══════════════════════════════════════════════════════
# 状态图构建器
# ═══════════════════════════════════════════════════════


def build_practice_graph():
    """
    构建训练状态图。

    依赖注入（由各节点从 LangGraph config["configurable"] 读取）:
      - model:      D 的 ModelGateway 实例
      - retriever:  B 的 HybridRetriever 实例
      - event_sink: D 的 AgentEventSink 实例

    用法:
      graph = build_practice_graph().compile(checkpointer=checkpointer)
      result = await graph.ainvoke(
          initial_state,
          config={
              "configurable": {
                  "thread_id": thread_id,
                  "model": model_instance,
                  "retriever": retriever_instance,
                  "event_sink": event_sink,
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

    builder.add_node("coordinator", coordinator_practice_node)
    builder.add_node("questioner", questioner_node)
    builder.add_node("wait_for_answer", wait_for_answer_node)
    builder.add_node("evaluator", evaluator_practice_node)
    builder.add_node("summary", summary_node)
    builder.add_node("error", _qa_error_node)

    builder.set_entry_point("coordinator")

    builder.add_edge("coordinator", "questioner")
    builder.add_edge("questioner", "wait_for_answer")
    builder.add_edge("wait_for_answer", "evaluator")
    builder.add_conditional_edges("evaluator", _route_practice, {
        "questioner": "questioner",
        "summary": "summary",
        "error": "error",
    })
    builder.add_edge("summary", END)
    builder.add_edge("error", END)

    return builder


def _route_practice(state: AgentState) -> str:
    return state.get("next_node", "summary")


# ═══════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════


def _format_refs(refs: list) -> str:
    if not refs:
        return "（无）"
    return "\n".join(
        "{} 第{}页: {}...".format(
            r.get("document_name", "?") if isinstance(r, dict) else getattr(r, "document_name", "?"),
            r.get("page_number", "?") if isinstance(r, dict) else getattr(r, "page_number", "?"),
            (r.get("excerpt", "") if isinstance(r, dict) else getattr(r, "excerpt", ""))[:100],
        )
        for r in refs[:8]
    )


def _build_source_label(q: GeneratedQuestionPrivate) -> str:
    if q.source_kind == "past_exam":
        ref = q.source_refs[0] if q.source_refs else {}
        name = ref.get("document_name", "") if isinstance(ref, dict) else getattr(ref, "document_name", "")
        no = ref.get("question_no", "") if isinstance(ref, dict) else getattr(ref, "question_no", "")
        return f"历年真题 · {name} 第{no}题" if ref else "历年真题"
    return "AI 变式题"


def _build_feedback(
    score: float, max_score: float, steps: list[dict],
    explanation: str, confidence: float, review_required: bool,
) -> dict:
    ratio = score / max_score if max_score > 0 else 0
    return {
        "score": score,
        "max_score": max_score,
        "score_ratio": ratio,
        "verdict": _verdict_label(ratio),
        "steps": steps,
        "explanation": explanation,
        "confidence": confidence,
        "review_required": review_required,
    }


def _verdict_label(ratio: float) -> str:
    if ratio >= 0.9:
        return "优秀"
    if ratio >= 0.7:
        return "良好"
    if ratio >= 0.5:
        return "需改进"
    return "需重点复习"
