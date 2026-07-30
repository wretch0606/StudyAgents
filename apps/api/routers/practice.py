"""Practice REST API — 严格对齐前端冻结契约 api(6).ts。

路径前缀: /api/practice/sessions
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.agent_run import AgentRun
from apps.api.db.models.answer_submission import AnswerSubmission
from apps.api.db.models.grade_result import GradeResult
from apps.api.db.models.mastery_record import MasteryRecord
from apps.api.db.models.practice_item import PracticeItem as PracticeItemModel
from apps.api.db.models.wrong_book_entry import WrongBookEntry
from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user, require_csrf
from apps.api.repositories import practice as repo
from apps.api.schemas.error import ApiError
from apps.api.schemas.practice import (
    ActiveRunRef,
    AnswerSubmissionRequest,
    CreatePracticeSessionResponse,
    FinishPracticeSessionResponse,
    KnowledgePointPerformance,
    PracticeItem,
    PracticeProgress,
    PracticeSession,
    PracticeSessionConfig,
    SessionSummary,
    SubmitAnswerResponse,
)
from apps.api.services.grading_service import GradingError, GradingService
from apps.api.services.training_service import TrainingError, TrainingService

router = APIRouter(prefix="/practice/sessions", tags=["practice"])


# ------------------------------------------------------------------
# 助手：从 PracticeItemModel 组装公开 PracticeItem DTO
# ------------------------------------------------------------------

def _to_practice_item(item: PracticeItemModel, progress: PracticeProgress) -> PracticeItem:
    pub = item.public_snapshot or {}
    return PracticeItem(
        item_id=str(item.id),
        question_version=item.question_version,
        order_no=item.order_no,
        source_kind=item.source_kind or "generated_variant",
        question_type=item.question_type,
        difficulty=pub.get("difficulty", 2),
        stem=item.stem,
        options=item.options or [],
        source_label=item.source_label or "",
        progress=progress,
    )


# ------------------------------------------------------------------
# 助手：将 DB PracticeSession 组装为公开 DTO
# ------------------------------------------------------------------

async def _build_practice_session(
    session: AsyncSession,
    ps,
    user_id: str,
    *,
    active_run: ActiveRunRef | None = None,
) -> PracticeSession:
    items = await repo.list_items_for_session(session, str(ps.id), user_id=user_id)
    total = len(items)

    # 查找第一个未提交的题作为 current_item
    current_item: PracticeItem | None = None
    completed = 0
    for item in items:
        result = await session.execute(
            sa_select(AnswerSubmission).where(AnswerSubmission.item_id == item.id),
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            if current_item is None:
                current_item = _to_practice_item(
                    item,
                    PracticeProgress(current=item.order_no, total=total),
                )
        else:
            completed += 1

    # 全部完成时 progress 指向最后一题
    if current_item is None and total > 0:
        progress = PracticeProgress(current=total, total=total)
    elif current_item is not None:
        progress = PracticeProgress(current=completed + 1, total=total)
    else:
        progress = PracticeProgress(current=0, total=0)

    filters_raw = ps.filters or {}
    filters_dto = PracticeSessionConfig(
        chapter_ids=filters_raw.get("chapter_ids", []),
        knowledge_point_ids=filters_raw.get("knowledge_point_ids", []),
        question_types=filters_raw.get("question_types", ["choice"]),
        difficulty=filters_raw.get("difficulty", 2),
        target_count=ps.target_count,
    )

    return PracticeSession(
        id=str(ps.id),
        user_id=str(ps.user_id),
        filters=filters_dto,
        target_count=ps.target_count,
        status=ps.status,
        current_item=current_item,
        progress=progress,
        active_run=active_run,
        created_at=ps.created_at.isoformat() if ps.created_at else "",
        updated_at=ps.updated_at.isoformat() if ps.updated_at else "",
    )


# ==================================================================
# POST /api/practice/sessions — 创建训练
# ==================================================================

@router.post("", response_model=CreatePracticeSessionResponse, status_code=201)
async def create_practice_session(
    body: PracticeSessionConfig,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> CreatePracticeSessionResponse:
    """创建训练会话并返回首题（同步模式 → state='ready'）。"""
    svc = TrainingService(session)
    try:
        result = await svc.create_training(
            user_id=user_id,
            chapter_ids=body.chapter_ids,
            question_types=body.question_types,
            difficulty=body.difficulty,
            count=body.target_count,
        )
    except TrainingError as exc:
        raise ApiError(
            exc.code, exc.message, status_code=422, retryable=exc.retryable,
        ) from exc

    ps = await repo.get_practice_session(session, result["session_id"], user_id=user_id)
    if ps is None:
        raise ApiError("INTERNAL", "会话创建后无法读取。", status_code=500, retryable=True)

    practice_session = await _build_practice_session(session, ps, user_id)
    return CreatePracticeSessionResponse(
        state="ready",
        session=practice_session,
    )


# ==================================================================
# GET /api/practice/sessions — 训练历史列表
# ==================================================================

@router.get("")
async def list_practice_sessions(
    user_id: str = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """查询本人训练历史（分页）。"""
    all_sessions = await repo.list_practice_sessions(
        session, user_id, limit=page_size, offset=(page - 1) * page_size,
    )
    # count total
    from sqlalchemy import func

    from apps.api.db.models.practice_session import PracticeSession as PsModel
    total_result = await session.execute(
        sa_select(func.count()).select_from(PsModel).where(
            PsModel.user_id == user_id,
        ),
    )
    total = total_result.scalar_one()

    items = []
    for ps in all_sessions:
        if status and ps.status != status:
            continue
        items.append(await _build_practice_session(session, ps, user_id))

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": [i.model_dump() for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ==================================================================
# GET /api/practice/sessions/{session_id} — 训练详情
# ==================================================================

@router.get("/{session_id}", response_model=PracticeSession)
async def get_practice_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PracticeSession:
    """获取训练详情（含 current_item）。"""
    ps = await repo.get_practice_session(session, session_id, user_id=user_id)
    if ps is None:
        raise ApiError(
            "RESOURCE_NOT_FOUND", "训练会话不存在。",
            status_code=404, retryable=False,
        )
    return await _build_practice_session(session, ps, user_id)


# ==================================================================
# POST /api/practice/sessions/{session_id}/answers — 提交答案
# ==================================================================

@router.post("/{session_id}/answers", response_model=SubmitAnswerResponse, status_code=201)
async def submit_answer(
    session_id: str,
    body: AnswerSubmissionRequest,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
) -> SubmitAnswerResponse:
    """提交答案并评分。X-Idempotency-Key 必填。"""
    svc = GradingService(session)
    # 把 raw_text 优先作为答案文本，回退到 selected_option_ids
    answer_text = body.raw_text or ""
    if not answer_text and body.selected_option_ids:
        answer_text = ",".join(body.selected_option_ids)

    try:
        svc.submit_answer  # ensure import works
        result = await svc.submit_answer(
            session_id=session_id,
            item_id=body.item_id,
            user_id=user_id,
            answer_text=answer_text,
            question_version=body.question_version,
            idempotency_key=x_idempotency_key,
        )
    except GradingError as exc:
        raise ApiError(
            exc.code, exc.message,
            status_code=422 if exc.code == "VERSION_MISMATCH" else 409,
            retryable=exc.retryable,
        ) from exc

    # 创建 AgentRun + AgentEvents 以对齐前端异步契约
    # 评分已同步完成 → run 状态为 "completed"，但通过持久化事件让 SSE 终端能正常关闭
    from apps.api.db.models.agent_event import AgentEvent as AgentEventModel
    from apps.api.services.sse_manager import sse_manager

    run_id = str(_uuid.uuid4())
    trace_id = _uuid.uuid4().hex[:16]
    now = datetime.now(UTC).replace(tzinfo=None)
    run = AgentRun(
        id=run_id,
        thread_id=result.submission_id,
        user_id=user_id,
        mode="practice",
        status="completed",
        run_type="practice_grade",
        trace_id=trace_id,
        timing={"total_ms": 0},
        started_at=now,
        completed_at=now,
    )
    session.add(run)
    await session.flush()  # 确保 run 先于 events 持久化

    # 写入两个最小事件：run.started + run.completed（SSE 历史回放 + 终态标记）
    summary = (
        f"score={result.score}/"
        f"{getattr(result, 'max_score', 10)} "
        f"verdict={getattr(result, 'verdict', 'N/A')}"
    )
    session.add(AgentEventModel(
        run_id=run_id,
        sequence_no=1,
        agent="evaluator",
        event_type="run.started",
        status="succeeded",
        summary="grading started",
    ))
    session.add(AgentEventModel(
        run_id=run_id,
        sequence_no=2,
        agent="evaluator",
        event_type="run.completed",
        status="succeeded",
        summary=summary[:2000],
    ))
    await session.commit()

    # 标记 SSE 完成，使晚订阅客户端能收到终态
    sse_manager.mark_completed(run_id)

    return SubmitAnswerResponse(
        run_id=run_id,
        event_url=f"/api/agent-runs/{run_id}/events",
    )


# ==================================================================
# POST /api/practice/sessions/{session_id}/finish — 结束训练
# ==================================================================

class PracticeSessionFinishRequest(BaseModel):
    """结束训练请求体 — status 区分正常完成与提前结束。"""
    status: Literal["completed", "cancelled"] = "completed"


@router.post("/{session_id}/finish", response_model=FinishPracticeSessionResponse)
async def finish_practice_session(
    session_id: str,
    body: PracticeSessionFinishRequest = PracticeSessionFinishRequest(),
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> FinishPracticeSessionResponse:
    """结束训练（幂等：重复结束返回相同结果）。"""
    ps = await repo.get_practice_session(session, session_id, user_id=user_id)
    if ps is None:
        raise ApiError(
            "RESOURCE_NOT_FOUND", "训练会话不存在。",
            status_code=404, retryable=False,
        )

    # 幂等：已结束则直接返回第一次的结果
    if ps.status in ("completed", "cancelled"):
        return FinishPracticeSessionResponse(
            session_id=session_id,
            status=ps.status,  # type: ignore[arg-type]
            summary_url=f"/api/practice/sessions/{session_id}/summary",
        )

    await repo.update_practice_session(
        session, session_id, user_id=user_id, status=body.status,
    )
    await session.commit()

    return FinishPracticeSessionResponse(
        session_id=session_id,
        status=body.status,
        summary_url=f"/api/practice/sessions/{session_id}/summary",
    )


# ==================================================================
# GET /api/practice/sessions/{session_id}/summary — 训练总结
# ==================================================================

@router.get("/{session_id}/summary", response_model=SessionSummary)
async def get_session_summary(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SessionSummary:
    """获取训练总结（基于已持久化评分数据）。"""
    ps = await repo.get_practice_session(session, session_id, user_id=user_id)
    if ps is None:
        raise ApiError(
            "RESOURCE_NOT_FOUND", "训练会话不存在。",
            status_code=404, retryable=False,
        )

    items = await repo.list_items_for_session(session, session_id, user_id=user_id)

    total_score = 0.0
    total_max_score = 0.0
    grades: list[dict] = []
    wrong_book_ids: list[str] = []
    kp_scores: dict[str, dict] = {}  # kp → {total, max, name}

    for item in items:
        # 查询该题的最新提交
        sub_result = await session.execute(
            sa_select(AnswerSubmission).where(
                AnswerSubmission.item_id == item.id,
            ).order_by(AnswerSubmission.attempt.desc()).limit(1),
        )
        sub = sub_result.scalar_one_or_none()
        if sub is None:
            continue

        # 查询评分
        grade_result = await session.execute(
            sa_select(GradeResult).where(
                GradeResult.submission_id == sub.id,
            ),
        )
        grade = grade_result.scalar_one_or_none()
        if grade is None:
            continue

        total_score += grade.total_score or 0
        total_max_score += 10  # default max per question
        grades.append({
            "id": str(grade.id),
            "answer_id": str(sub.id),
            "score": grade.total_score or 0,
            "max_score": 10,
            "confidence": grade.confidence or 0,
            "review_required": grade.review_required,
        })

        # 查询错题
        wb_result = await session.execute(
            sa_select(WrongBookEntry).where(
                WrongBookEntry.submission_id == sub.id,
            ),
        )
        wb = wb_result.scalar_one_or_none()
        if wb is not None:
            wrong_book_ids.append(str(wb.id))

        # 知识点表现（从 mastery_change_log 推断）
        kp = (item.public_snapshot or {}).get("source_kind", "practice")
        kp_name = (item.public_snapshot or {}).get("source_label", kp)
        if kp not in kp_scores:
            kp_scores[kp] = {"total": 0, "max": 0, "name": kp_name}
        kp_scores[kp]["total"] += grade.total_score or 0
        kp_scores[kp]["max"] += 10

    # 组装知识点表现（含真实 mastery_change）
    kp_perf = []
    for kp, data in kp_scores.items():
        # 查找对应 mastery record
        mr_result = await session.execute(
            sa_select(MasteryRecord).where(
                MasteryRecord.user_id == user_id,
                MasteryRecord.knowledge_point == kp,
            ),
        )
        mr = mr_result.scalar_one_or_none()
        current_mastery = mr.current_level if mr else 0.5

        # 从 MasteryChangeLog 计算本次训练的 mastery 变化
        from apps.api.db.models.mastery_change_log import MasteryChangeLog
        mastery_change = 0.0
        if mr is not None:
            # 找本次 session 中与该 mastery record 相关的变更日志
            log_result = await session.execute(
                sa_select(MasteryChangeLog).where(
                    MasteryChangeLog.mastery_id == mr.id,
                    MasteryChangeLog.change_reason.in_(
                        ("grade_result", "wrong_answer"),
                    ),
                ).order_by(MasteryChangeLog.created_at.asc()),
            )
            logs = log_result.scalars().all()
            if logs:
                first_before = logs[0].before_level
                last_after = logs[-1].after_level
                mastery_change = round(last_after - first_before, 4)

        kp_perf.append(KnowledgePointPerformance(
            knowledge_point_id=kp,
            knowledge_point_name=data["name"],
            mastery=current_mastery,
            mastery_change=mastery_change,
        ))

    # 生成建议
    suggestion = None
    if total_max_score > 0:
        ratio = total_score / total_max_score
        if ratio < 0.6:
            suggestion = "建议重新复习相关知识点，重点关注错题中的薄弱环节。"
        elif ratio < 0.8:
            suggestion = "表现良好，继续巩固错题涉及的知识点。"
        else:
            suggestion = "掌握扎实，可以尝试更高难度的训练。"

    return SessionSummary(
        session_id=session_id,
        total_score=total_score,
        total_max_score=total_max_score,
        grades=grades,
        knowledge_point_performance=kp_perf,
        wrong_book_entry_ids=wrong_book_ids,
        suggestion=suggestion,
    )
