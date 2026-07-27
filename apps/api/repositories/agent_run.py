"""Agent Run 与 Agent Event 仓储 — 纯数据库操作。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.agent_event import AgentEvent as AgentEventModel
from apps.api.db.models.agent_run import AgentRun as AgentRunModel

# ---- Run ----

async def create_run(
    session: AsyncSession,
    *,
    run_id: str,
    thread_id: str,
    user_id: str,
    mode: str,
) -> AgentRunModel:
    run = AgentRunModel(id=run_id, thread_id=thread_id, user_id=user_id, mode=mode)
    session.add(run)
    await session.flush()
    return run


async def get_run(
    session: AsyncSession, run_id: str, *, user_id: str,
) -> AgentRunModel | None:
    result = await session.execute(
        select(AgentRunModel).where(
            AgentRunModel.id == run_id,
            AgentRunModel.user_id == user_id,
        ),
    )
    return result.scalar_one_or_none()


async def update_run_status(
    session: AsyncSession, run_id: str, status: str, *, user_id: str, **kwargs,
) -> None:
    run = await get_run(session, run_id, user_id=user_id)
    if run is None:
        return
    run.status = status
    for key, value in kwargs.items():
        setattr(run, key, value)
    await session.flush()


# ---- Events ----

async def get_next_sequence(session: AsyncSession, run_id: str) -> int:
    """获取下一次事件的 sequence_no（最大序号 +1）。"""
    result = await session.execute(
        select(AgentEventModel.sequence_no)
        .where(AgentEventModel.run_id == run_id)
        .order_by(AgentEventModel.sequence_no.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    return (last + 1) if last is not None else 0


async def insert_event(
    session: AsyncSession,
    *,
    run_id: str,
    sequence_no: int,
    agent: str,
    event_type: str,
    status: str,
    summary: str,
    source_refs: list[dict],
    duration_ms: int | None = None,
    private_payload: dict | None = None,
) -> AgentEventModel:
    event = AgentEventModel(
        run_id=run_id,
        sequence_no=sequence_no,
        agent=agent,
        event_type=event_type,
        status=status,
        summary=summary,
        source_refs=source_refs,
        duration_ms=duration_ms,
        private_payload=private_payload,
    )
    session.add(event)
    await session.flush()
    return event


async def get_events_since(
    session: AsyncSession, run_id: str, *, user_id: str, since_seq: int = -1,
) -> list[AgentEventModel]:
    """获取指定 run 中 sequence_no > since_seq 的事件（用于 SSE 补发）。

    Owner isolation: 先通过 get_run 验证属主，再查询事件。
    """
    run = await get_run(session, run_id, user_id=user_id)
    if run is None:
        return []
    result = await session.execute(
        select(AgentEventModel)
        .where(
            AgentEventModel.run_id == run_id,
            AgentEventModel.sequence_no > since_seq,
        )
        .order_by(AgentEventModel.sequence_no)
    )
    return list(result.scalars().all())
