"""Practice 仓储 — 训练会话和题目 CRUD。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.practice_item import PracticeItem
from apps.api.db.models.practice_session import PracticeSession

# ---- Session ----

async def create_practice_session(
    session: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    thread_id: str,
    title: str | None = None,
    total_questions: int = 5,
    filters: dict | None = None,
    target_count: int = 5,
) -> PracticeSession:
    ps = PracticeSession(
        id=session_id,
        user_id=user_id,
        thread_id=thread_id,
        title=title,
        status="active",
        mode="practice",
        filters=filters,
        target_count=target_count,
    )
    session.add(ps)
    await session.flush()
    return ps


async def get_practice_session(
    session: AsyncSession, session_id: str, *, user_id: str,
) -> PracticeSession | None:
    result = await session.execute(
        select(PracticeSession).where(
            PracticeSession.id == session_id,
            PracticeSession.user_id == user_id,
        ),
    )
    return result.scalar_one_or_none()


async def list_practice_sessions(
    session: AsyncSession, user_id: str, *, limit: int = 50, offset: int = 0,
) -> list[PracticeSession]:
    result = await session.execute(
        select(PracticeSession)
        .where(PracticeSession.user_id == user_id)
        .order_by(PracticeSession.updated_at.desc())
        .limit(limit).offset(offset),
    )
    return list(result.scalars().all())


async def update_practice_session(
    session: AsyncSession, session_id: str, *, user_id: str, **kwargs,
) -> None:
    ps = await get_practice_session(session, session_id, user_id=user_id)
    if ps is None:
        return
    for key, value in kwargs.items():
        if hasattr(ps, key):
            setattr(ps, key, value)
    await session.flush()


# ---- Items ----

async def insert_practice_item(
    session: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    order_no: int,
    question_type: str,
    stem: str,
    options: dict | None = None,
    source_kind: str = "generated",
    source_label: str | None = None,
    question_version: str = "1.0",
    public_snapshot: dict | None = None,
    private_snapshot: dict | None = None,
    run_id: str | None = None,
) -> PracticeItem:
    item = PracticeItem(
        session_id=session_id,
        user_id=user_id,
        order_no=order_no,
        question_type=question_type,
        stem=stem or "",
        options=options,
        source_kind=source_kind,
        source_label=source_label,
        question_version=question_version,
        public_snapshot=public_snapshot or {},
        private_snapshot=private_snapshot,
        run_id=run_id,
    )
    session.add(item)
    await session.flush()
    return item


async def get_item_by_order(
    session: AsyncSession, session_id: str, order_no: int, *, user_id: str,
) -> PracticeItem | None:
    result = await session.execute(
        select(PracticeItem).where(
            PracticeItem.session_id == session_id,
            PracticeItem.order_no == order_no,
            PracticeItem.user_id == user_id,
        ),
    )
    return result.scalar_one_or_none()


async def get_next_order_for_session(
    session: AsyncSession, session_id: str,
) -> int:
    result = await session.execute(
        select(PracticeItem.order_no)
        .where(PracticeItem.session_id == session_id)
        .order_by(PracticeItem.order_no.desc())
        .limit(1),
    )
    last = result.scalar_one_or_none()
    return (last + 1) if last is not None else 1


async def list_items_for_session(
    session: AsyncSession, session_id: str, *, user_id: str,
) -> list[PracticeItem]:
    result = await session.execute(
        select(PracticeItem)
        .where(
            PracticeItem.session_id == session_id,
            PracticeItem.user_id == user_id,
        )
        .order_by(PracticeItem.order_no),
    )
    return list(result.scalars().all())


async def count_items_in_session(
    session: AsyncSession, session_id: str,
) -> int:
    from sqlalchemy import func

    result = await session.execute(
        select(func.count()).where(
            PracticeItem.session_id == session_id,
        ),
    )
    return result.scalar_one()
