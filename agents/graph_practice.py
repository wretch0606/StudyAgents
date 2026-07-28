"""
训练状态图（Practice Mode）— V1.0

LangGraph 固定状态图，对应开发文档 6.4 节（图 5）。

节点流转:
  START → coordinator → questioner → [WaitForAnswer via interrupt]
                                           │
                                           ▼
                                        evaluator → [more?]
                                           │           ├─ yes → questioner
                                           │           └─ no  → summary → END

依赖（D / B 提供）:
  - ModelGateway:     from apps.api.services.model_gateway
  - AgentEventSink:   from apps.api.services.agent_event_sink
  - AgentEventDraft:  from apps.api.schemas.agent
  - HybridRetriever:  from worker.retrieval.retriever (B 提供)
  - LangGraph interrupt:  D 的 PostgreSQL checkpointer
"""
from __future__ import annotations

import uuid
from typing import Any

from .state import AgentState, RetrievalFilters, SourceRef

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

from .graph import _build_messages, _emit, _error_return, _limits_exceeded, MAX_MODEL_CALLS, MAX_NODE_HOPS
from .schemas import PROMPT_VERSIONS, CoordinatorDecision, GeneratedQuestionPrivate, GradeResultPrivate, PracticeFeedback, StepFeedbackPublic
from .rules.grading import grade_choice, grade_fill_blank, validate_step_scores, update_mastery, adjust_difficulty

# ── 提示词 ──
from .prompts.coordinator import SYSTEM_PROMPT as COORDINATOR_SYSTEM, USER_MESSAGE_TEMPLATE as COORDINATOR_USER
from .prompts.questioner import SYSTEM_PROMPT as QUESTIONER_SYSTEM, USER_MESSAGE_TEMPLATE as QUESTIONER_USER
from .prompts.evaluator import SYSTEM_PROMPT as EVALUATOR_SYSTEM, USER_MESSAGE_TEMPLATE as EVALUATOR_USER

# ═══════════════════════════════════════════════════════
# 节点函数
# ═══════════════════════════════════════════════════════


async def coordinator_practice_node(state: AgentState, model: ModelGateway) -> dict[str, Any]:
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
        summary=f"协调 Agent 开始专项训练：{filters.get('chapter_ids', ['全部'])}章节，{filters.get('question_types', ['全部'])}题型，难度{filters.get('difficulty', 2)}，共{target_count}题",
    )

    # 初始化训练状态
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
    model: ModelGateway,
    retriever: Any,
) -> dict[str, Any]:
    """
    出题节点：真题优先 → 变式生成。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1
    state["model_calls"] = state.get("model_calls", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    filters = state.get("filters", {})
    exclude_ids = state.get("exclude_chunk_ids", [])

    # Step 1: 以 admin 身份检索真题候选（获取含答案的块）
    exam_result = await retriever.retrieve(
        query="",
        filters=RetrievalFilters(
            chapter_ids=filters.get("chapter_ids", []),
            question_types=filters.get("question_types"),
            difficulty=filters.get("difficulty"),
            exclude_chunk_ids=exclude_ids,
            knowledge_point_ids=filters.get("knowledge_point_ids", []),
            year=filters.get("year"),
        ) if filters else RetrievalFilters(),
        user_role="admin",  # ⚠️ admin 可获取含答案的私有块
    )

    exam_candidates = exam_result.source_refs[:8] if hasattr(exam_result, 'source_refs') else []

    # Step 2: LLM 出题
    user_msg = QUESTIONER_USER.format(
        knowledge_points=filters.get("knowledge_point_ids", ["全部"]),
        difficulty=filters.get("difficulty", 2),
        question_type=filters.get("question_types", ["calculation"])[0] if filters.get("question_types") else "calculation",
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
        # 换一道真题或重试一次
        await _emit(state=state, agent="questioner", event_type="agent.summary", status="succeeded",
                    summary=f"出题 Agent 生成题目置信度 {question.confidence} < 0.8，尝试重新选择")
        # 回退到真题（如果有）
        if exam_candidates:
            # 选一道真题直接使用（此处简化，实际应调用 LLM 重新适配）
            await _emit(state=state, agent="questioner", event_type="agent.summary", status="succeeded",
                        summary="回退到可信真题")

    # Step 4: 构造公开题目和私有数据
    item_id = question.question_id or str(uuid.uuid4())
    order_no = state.get("current_item_index", 0) + 1

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

    # 存储完整题目（含私有答案）到 practice_items
    practice_items = state.get("practice_items", [])
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
    )

    return {
        "practice_items": practice_items,
        "current_item_index": order_no,  # 1-based 在 state 中
        "current_public_question": public_item,  # 公开给前端
        "next_node": "wait_for_answer",
    }


async def wait_for_answer_node(state: AgentState) -> dict[str, Any]:
    """
    等待用户提交答案。使用 LangGraph interrupt 暂停。

    D 需配置 checkpointer 以支持 interrupt。
    中断后通过 graph.ainvoke(..., config) 恢复，传入 Command(resume=user_answer)。
    """
    from langgraph.types import interrupt

    # 暂停，等待用户提交
    user_answer = interrupt("waiting_for_answer")

    # 恢复后，user_answer 是用户提交的文本
    state["user_answer"] = user_answer

    await _emit(
        state=state,
        agent="system",
        event_type="run.waiting_user",
        status="waiting_user",
        summary=f"收到第 {state.get('current_item_index', 0)} 题答案",
    )

    return {
        "user_answer": user_answer,
        "next_node": "evaluator",
    }


async def evaluator_practice_node(state: AgentState, model: ModelGateway) -> dict[str, Any]:
    """
    评测节点（训练模式）：客观题规则评分 / 主观题 LLM 评分。
    """
    state["node_hops"] = state.get("node_hops", 0) + 1

    if _limits_exceeded(state):
        return _error_return(state, "AGENT_LIMIT_EXCEEDED", "超过调用或节点上限", False)

    practice_items = state.get("practice_items", [])
    idx = state.get("current_item_index", 1) - 1  # 转为 0-based
    if idx < 0 or idx >= len(practice_items):
        return _error_return(state, "PRACTICE_STATE_CONFLICT", "题目索引越界", True)

    current = practice_items[idx]
    user_answer = state.get("user_answer", "")
    private = current["private"]
    question_type = current["question_type"]

    # ── 客观题：规则评分，不调 LLM ──
    if question_type == "choice":
        grade = grade_choice(user_answer, private["expected_answer"], 0)
        feedback = _build_feedback(grade["score"], 0, [{"status": "met" if grade["met"] else "not_met", "text": grade["feedback"]}], "", grade["confidence"], False)
        return _finish_item(state, current, feedback, grade)

    if question_type == "fill_blank":
        rubric = private.get("rubric", [])
        max_score = sum(r["max_score"] for r in rubric) if rubric else 0
        acceptable = rubric[0].get("acceptable_forms", []) if rubric else None
        grade = grade_fill_blank(user_answer, private["expected_answer"], acceptable, max_score)
        feedback = _build_feedback(grade["score"], max_score, [{"status": "met" if grade["met"] else "not_met", "text": grade["feedback"]}], "", grade["confidence"], False)
        return _finish_item(state, current, feedback, grade)

    # ── 主观题：LLM 评分 ──
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
        await _emit(state=state, agent="evaluator", event_type="agent.summary", status="failed",
                    summary=f"评分校验失败: {validation['violations']}")

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
    )

    return _finish_item(state, current, feedback.model_dump(), {"score": final_score, "max_score": max_total, "confidence": grade_result.confidence})


def _finish_item(state: AgentState, current: dict, feedback: dict, grade: dict) -> dict:
    """记录本题评分，决定下一题还是结束"""
    practice_items = state.get("practice_items", [])
    idx = state.get("current_item_index", 1) - 1
    practice_items[idx]["feedback"] = feedback
    practice_items[idx]["grade"] = grade

    current_idx = state.get("current_item_index", 1)
    target = state.get("target_count", 5)
    scores = state.get("practice_scores", []) + [grade.get("score_ratio", grade.get("score", 0) / max(grade.get("max_score", 1), 1))]

    if current_idx >= target:
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
            "mastery_updates": [],  # 由调用方按实际知识点计算
        }
        return {
            "practice_items": practice_items,
            "current_feedback": feedback,
            "practice_summary": summary,
            "next_node": "summary",
        }
    else:
        # 继续下一题
        return {
            "practice_items": practice_items,
            "current_feedback": feedback,
            "current_item_index": current_idx + 1,
            "exclude_chunk_ids": state.get("exclude_chunk_ids", []) + [c.get("chunk_id", "") for c in current.get("source_refs", [])],
            "next_node": "questioner",
        }


async def summary_node(state: AgentState) -> dict[str, Any]:
    """训练结束：输出总结"""
    s = state.get("practice_summary", {})
    public_response = (
        f"**训练完成**\n\n"
        f"总分：{s.get('total_score', 0)} / {s.get('total_max', 0)} "
        f"（{s.get('total_ratio', 0) * 100:.0f}%）\n"
        f"题目数：{s.get('items_count', 0)}\n\n"
        f"错题已自动加入错题本，可随时复习。"
    )
    await _emit(state=state, agent="system", event_type="run.completed", status="succeeded", summary="训练完成")
    return {"public_response": public_response, "next_node": "__end__"}


# ═══════════════════════════════════════════════════════
# 状态图构建器
# ═══════════════════════════════════════════════════════


def build_practice_graph():
    """
    构建训练状态图。

    需要 D 配置 PostgreSQL checkpointer 以支持 interrupt。
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
    builder.add_node("error", __import__("agents.graph", fromlist=["error_node"]).error_node)

    builder.set_entry_point("coordinator")

    builder.add_edge("coordinator", "questioner")
    builder.add_edge("questioner", "wait_for_answer")
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
        f"[{i+1}] {r.get('document_name', '?')} 第{r.get('page_number', '?')}页: {r.get('excerpt', '')[:100]}..."
        for i, r in enumerate(refs[:8])
    )


def _build_source_label(q: GeneratedQuestionPrivate) -> str:
    if q.source_kind == "past_exam":
        ref = q.source_refs[0] if q.source_refs else {}
        return f"历年真题 · {ref.get('document_name', '')} 第{ref.get('question_no', '?')}题" if ref else "历年真题"
    return "AI 变式题"


def _build_feedback(score: float, max_score: float, steps: list[dict], explanation: str, confidence: float, review_required: bool) -> dict:
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
