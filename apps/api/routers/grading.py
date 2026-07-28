"""Grading REST API — 答案提交和评分。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user, require_csrf
from apps.api.schemas.error import ApiError
from apps.api.schemas.grading import SubmitAnswerRequest, SubmitAnswerResponse
from apps.api.services.grading_service import GradingError, GradingService

router = APIRouter(prefix="/training", tags=["grading"])


@router.post("/{session_id}/submit", response_model=SubmitAnswerResponse)
async def submit_answer(
    session_id: str,
    body: SubmitAnswerRequest,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
) -> SubmitAnswerResponse:
    """提交答案并评分。X-Idempotency-Key 必填。"""
    svc = GradingService(session)
    try:
        return await svc.submit_answer(
            session_id=session_id,
            item_id=body.item_id,
            user_id=user_id,
            answer_text=body.answer_text,
            question_version=body.question_version,
            idempotency_key=x_idempotency_key,
        )
    except GradingError as exc:
        raise ApiError(
            exc.code, exc.message,
            status_code=422 if exc.code == "VERSION_MISMATCH" else 409,
            retryable=exc.retryable,
        ) from exc
