"""Learning-Summary API — 对齐前端冻结契约 api(6).ts。

GET /api/learning-summary — 查询本人掌握度与近期学习表现
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.grade_result import GradeResult
from apps.api.db.models.mastery_change_log import MasteryChangeLog
from apps.api.db.models.mastery_record import MasteryRecord as MRModel
from apps.api.db.models.practice_session import PracticeSession
from apps.api.db.models.wrong_book_entry import WrongBookEntry as WBModel
from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user
from apps.api.schemas.practice import LearningSummary, MasteryRecord

router = APIRouter(prefix="/learning-summary", tags=["learning"])

# "近期" 时间窗口：开发文档未明确定义，采用 7 天作为合理的默认值
RECENT_DAYS = 7


# ==================================================================
# GET /api/learning-summary
# ==================================================================

@router.get("", response_model=LearningSummary)
async def get_learning_summary(
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> LearningSummary:
    """查询当前用户的学习摘要。"""
    # 掌握度记录
    mr_result = await session.execute(
        sa_select(MRModel).where(MRModel.user_id == user_id),
    )
    mastery_rows = mr_result.scalars().all()

    mastery_records = []
    for mr in mastery_rows:
        # 获取最近一次变更原因
        reason = None
        log_result = await session.execute(
            sa_select(MasteryChangeLog).where(
                MasteryChangeLog.mastery_id == mr.id,
            ).order_by(MasteryChangeLog.created_at.desc()).limit(1),
        )
        last_log = log_result.scalar_one_or_none()
        if last_log is not None:
            reason = last_log.change_reason

        mastery_records.append(MasteryRecord(
            user_id=str(mr.user_id),
            knowledge_point_id=mr.knowledge_point,
            mastery=mr.current_level,
            streaks=mr.streak,
            reason=reason,
            updated_at=mr.updated_at.isoformat() if mr.updated_at else None,
        ))

    # 错题统计
    pending_count = (await session.execute(
        sa_select(func.count()).select_from(WBModel).where(
            WBModel.user_id == user_id,
            WBModel.status == "pending",
        ),
    )).scalar_one()

    reviewing_count = (await session.execute(
        sa_select(func.count()).select_from(WBModel).where(
            WBModel.user_id == user_id,
            WBModel.status == "reviewing",
        ),
    )).scalar_one()

    # 近期表现
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=RECENT_DAYS)

    recent_grades = (await session.execute(
        sa_select(GradeResult).where(
            GradeResult.user_id == user_id,
            GradeResult.created_at >= cutoff,
            GradeResult.total_score.isnot(None),
            GradeResult.confidence > 0,
            GradeResult.review_required.is_(False),
        ),
    )).scalars().all()

    recent_accuracy = None
    if recent_grades:
        ratios = [
            (g.total_score or 0) / max(10, 1)
            for g in recent_grades
        ]
        recent_accuracy = round(sum(ratios) / len(ratios), 4)

    recent_session_count_result = await session.execute(
        sa_select(func.count()).select_from(PracticeSession).where(
            PracticeSession.user_id == user_id,
            PracticeSession.created_at >= cutoff,
        ),
    )
    recent_session_count = recent_session_count_result.scalar_one()

    # 摘要文本（确定性模板）
    summary_text = _build_summary_text(
        mastery_count=len(mastery_records),
        pending_wrong=pending_count,
        reviewing_wrong=reviewing_count,
        accuracy=recent_accuracy,
    )

    return LearningSummary(
        user_id=user_id,
        mastery_records=mastery_records,
        pending_wrong_count=pending_count,
        reviewing_wrong_count=reviewing_count,
        recent_accuracy=recent_accuracy,
        recent_session_count=recent_session_count if recent_session_count > 0 else None,
        summary_text=summary_text,
    )


def _build_summary_text(
    *,
    mastery_count: int,
    pending_wrong: int,
    reviewing_wrong: int,
    accuracy: float | None,
) -> str:
    parts = [f"已覆盖 {mastery_count} 个知识点。"]
    if accuracy is not None:
        pct = round(accuracy * 100)
        parts.append(f"近期正确率 {pct}%。")
    if pending_wrong > 0:
        parts.append(f"待复习错题 {pending_wrong} 道。")
    if reviewing_wrong > 0:
        parts.append(f"复习中错题 {reviewing_wrong} 道。")
    if pending_wrong == 0 and reviewing_wrong == 0:
        parts.append("暂无错题，继续保持！")
    return "".join(parts)
