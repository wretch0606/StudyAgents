"""Training REST API — 创建训练、获取下一题、查询进度。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user, require_csrf
from apps.api.schemas.error import ApiError
from apps.api.schemas.training import (
    CreateTrainingRequest,
    CreateTrainingResponse,
    NextQuestionResponse,
    TrainingProgressResponse,
)
from apps.api.services.training_service import TrainingError, TrainingService

router = APIRouter(prefix="/training", tags=["training"])


# ---- POST /api/training ----

@router.post("", response_model=CreateTrainingResponse, status_code=201)
async def create_training(
    body: CreateTrainingRequest,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> CreateTrainingResponse:
    """创建训练会话。"""
    svc = TrainingService(session)
    try:
        result = await svc.create_training(
            user_id=user_id,
            chapter_ids=body.chapter_ids,
            question_types=body.question_types,
            difficulty=body.difficulty,
            count=body.count,
        )
        return CreateTrainingResponse(
            session_id=result["session_id"],
            thread_id=result["thread_id"],
            total_questions=result["total_questions"],
        )
    except TrainingError as exc:
        raise ApiError(
            exc.code, exc.message, status_code=422, retryable=exc.retryable,
        ) from exc


# ---- GET /api/training/{session_id}/next ----

@router.get("/{session_id}/next", response_model=NextQuestionResponse)
async def get_next_question(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NextQuestionResponse:
    """获取当前未完成题目（公开 DTO，不含答案）。"""
    svc = TrainingService(session)
    try:
        result = await svc.get_next_question(
            session_id=session_id, user_id=user_id,
        )
        if result is None:
            raise ApiError(
                "RESOURCE_NOT_FOUND",
                "无更多题目或会话不存在。",
                status_code=404, retryable=False,
            )
        return result
    except TrainingError as exc:
        raise ApiError(
            exc.code, exc.message, status_code=404, retryable=exc.retryable,
        ) from exc


# ---- GET /api/training/{session_id} ----

@router.get("/{session_id}", response_model=TrainingProgressResponse)
async def get_training_progress(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TrainingProgressResponse:
    """查询训练进度。"""
    svc = TrainingService(session)
    try:
        result = await svc.get_session_progress(
            session_id=session_id, user_id=user_id,
        )
        return TrainingProgressResponse(**result)
    except TrainingError as exc:
        raise ApiError(
            exc.code, exc.message, status_code=404, retryable=exc.retryable,
        ) from exc
