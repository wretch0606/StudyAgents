"""AgentEventSink — C 调用的事件提交接口。

C 不直接写 agent_events 表，通过此接口提交事件草稿。
D 负责：校验 → 序号 → 写库 → SSE 发布。

真实的 C 调用示例：
    from apps.api.services.agent_event_sink import agent_event_sink
    from apps.api.schemas.agent import AgentEventDraft

    event = AgentEventDraft(
        agent="coordinator",
        event_type="run.started",
        status="running",
        summary="QA run started",
        source_refs=[],
    )
    public_event = await agent_event_sink.emit(
        run_id="<uuid>",
        event=event,
        db_session=db_session,
    )
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy import select

from apps.api.db.models.agent_run import AgentRun as AgentRunModel
from apps.api.repositories import agent_run as run_repo
from apps.api.schemas.agent import (
    MAX_SOURCE_REFS,
    MAX_SUMMARY_LENGTH,
    AgentEvent,
    AgentEventDraft,
)
from apps.api.services.event_types import AGENT_EVENT_TYPES
from apps.api.services.sse_manager import _to_public, sse_manager

logger = logging.getLogger(__name__)


class AgentEventSinkProtocol(Protocol):
    """AgentEventSink 协议 — 内存测试实现和数据库实现均遵守此接口。"""

    async def emit(
        self, *, run_id: str, event: AgentEventDraft, db_session,
    ) -> AgentEvent: ...


class AgentEventSink:
    """C 通过此接口提交事件，D 完成持久化 + 推送。

    实现 AgentEventSinkProtocol：
    - 校验 event_type 枚举
    - 校验 summary / source_refs 大小
    - 锁 run 行确保并发安全序号
    - 写库成功后才发布 SSE
    """

    async def emit(
        self,
        *,
        run_id: str,
        event: AgentEventDraft,
        db_session,  # AsyncSession
    ) -> AgentEvent:
        """校验 → 生成序号 → 写库 → 发布 SSE。

        并发安全：通过对 agent_runs 行加 FOR UPDATE 锁序列化同一 run 的并发 emit，
        确保 sequence_no 单调不重复。
        """
        # 1. 校验 event_type 枚举
        if event.event_type not in AGENT_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type: {event.event_type!r}. "
                f"Allowed: {sorted(AGENT_EVENT_TYPES)}",
            )

        # 2. 校验 summary 长度（双重保险 — Pydantic 已做第一层）
        if len(event.summary) > MAX_SUMMARY_LENGTH:
            raise ValueError(
                f"Summary too long: {len(event.summary)} > {MAX_SUMMARY_LENGTH}",
            )

        # 3. 校验 source_refs 数量（双重保险 — Pydantic 已做第一层）
        if len(event.source_refs) > MAX_SOURCE_REFS:
            raise ValueError(
                f"Too many source_refs: {len(event.source_refs)} > {MAX_SOURCE_REFS}",
            )

        # 4. 锁 run 行 → 确保并发 emit 序列化
        await db_session.execute(
            _select_run_for_update(run_id),
        )

        # 5. 序列号（在锁保护下）
        seq = await run_repo.get_next_sequence(db_session, run_id)

        # 6. 写库
        db_event = await run_repo.insert_event(
            db_session,
            run_id=run_id,
            sequence_no=seq,
            agent=event.agent,
            event_type=event.event_type,
            status=event.status,
            summary=event.summary,
            source_refs=event.source_refs,
            duration_ms=event.duration_ms,
        )
        await db_session.commit()

        # 7. 发布 SSE（写库成功后才允许发布）
        public = _to_public(db_event)
        try:
            await sse_manager.publish(run_id, public)
        except Exception:
            logger.exception("SSE publish failed for run_id=%s seq=%d", run_id, seq)

        return public


def _select_run_for_update(run_id: str):
    """构建 FOR UPDATE 查询以锁住 agent_runs 行。"""
    return (
        select(AgentRunModel)
        .where(AgentRunModel.id == run_id)
        .with_for_update()
    )


# 模块级单例 — C 的真实 import 路径
agent_event_sink = AgentEventSink()
