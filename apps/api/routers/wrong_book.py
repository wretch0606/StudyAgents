"""Wrong-Book REST API — 对齐前端冻结契约 api(6).ts。

GET  /api/wrong-book      — 分页查询本人错题
PATCH /api/wrong-book/{id} — 更新备注或标记待复习
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.wrong_book_entry import WrongBookEntry as WBModel
from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user, require_csrf
from apps.api.schemas.error import ApiError
from apps.api.schemas.practice import (
    UpdateWrongBookRequest,
    WrongBookEntry,
)

router = APIRouter(prefix="/wrong-book", tags=["wrong-book"])


# ------------------------------------------------------------------
# 助手：DB 模型 → 公开 DTO
# ------------------------------------------------------------------

def _to_dto(wb: WBModel) -> WrongBookEntry:
    return WrongBookEntry(
        id=str(wb.id),
        user_id=str(wb.user_id),
        question_id=str(wb.item_id),
        question_stem=wb.stem_snapshot,
        question_type=wb.question_type,
        source_kind=wb.source_kind or "",
        source_label=wb.source_label or "",
        knowledge_point_id=wb.knowledge_point_id or "",
        status=wb.status or "pending",
        first_error_at=wb.first_error_at.isoformat() if wb.first_error_at else None,
        last_error_at=wb.last_error_at.isoformat() if wb.last_error_at else None,
        error_count=wb.error_count or 1,
        last_score=wb.last_score,
        last_max_score=wb.last_max_score,
        next_review_at=wb.next_review_at.isoformat() if wb.next_review_at else None,
        note=wb.note,
        created_at=wb.created_at.isoformat() if wb.created_at else None,
        updated_at=wb.updated_at.isoformat() if wb.updated_at else None,
    )


# ==================================================================
# GET /api/wrong-book — 错题本列表
# ==================================================================

@router.get("")
async def list_wrong_book(
    user_id: str = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    chapter_id: str | None = Query(default=None),
    knowledge_point_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """查询当前用户的错题本（分页 + 筛选）。"""
    # 防御：直接调用（非 HTTP）时 Query 默认值是 Query 对象
    if not isinstance(page, int):
        page = 1
    if not isinstance(page_size, int):
        page_size = 20
    if not isinstance(status, str):
        status = None
    if not isinstance(knowledge_point_id, str):
        knowledge_point_id = None
    if not isinstance(chapter_id, str):
        chapter_id = None

    conditions = [WBModel.user_id == user_id]
    if status:
        conditions.append(WBModel.status == status)
    if knowledge_point_id:
        conditions.append(WBModel.knowledge_point_id == knowledge_point_id)
    if chapter_id:
        conditions.append(WBModel.source_label.ilike(f"%{chapter_id}%"))

    # 计数
    total_result = await session.execute(
        sa_select(func.count()).select_from(WBModel).where(*conditions),
    )
    total = total_result.scalar_one()

    # 分页查询
    items_result = await session.execute(
        sa_select(WBModel)
        .where(*conditions)
        .order_by(WBModel.last_error_at.desc().nullslast())
        .offset((page - 1) * page_size)
        .limit(page_size),
    )
    items = [_to_dto(wb) for wb in items_result.scalars().all()]

    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": [i.model_dump() for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ==================================================================
# PATCH /api/wrong-book/{entry_id} — 更新错题条目
# ==================================================================

@router.patch("/{entry_id}", response_model=WrongBookEntry)
async def update_wrong_book(
    entry_id: str,
    body: UpdateWrongBookRequest,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> WrongBookEntry:
    """更新错题条目（仅允许 status=pending|reviewing 和 note）。"""
    result = await session.execute(
        sa_select(WBModel).where(
            WBModel.id == entry_id,
            WBModel.user_id == user_id,
        ),
    )
    wb = result.scalar_one_or_none()
    if wb is None:
        raise ApiError(
            "RESOURCE_NOT_FOUND", "错题条目不存在。",
            status_code=404, retryable=False,
        )

    if body.status is not None:
        if body.status not in ("pending", "reviewing"):
            raise ApiError(
                "INVALID_STATUS",
                "只允许设置为 pending 或 reviewing。",
                status_code=422, retryable=False,
            )
        wb.status = body.status

    if body.note is not None:
        wb.note = body.note

    await session.commit()
    await session.refresh(wb)
    return _to_dto(wb)
