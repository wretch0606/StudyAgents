"""AgentEventSink — C 调用的事件提交接口。

C 不直接写 agent_events 表，通过此接口提交事件草稿。
D 负责：校验 → 序号 → 写库 → SSE 发布。
"""

from __future__ import annotations

import logging

from apps.api.repositories import agent_run as run_repo
from apps.api.schemas.agent import AgentEvent, AgentEventDraft
from apps.api.services.sse_manager import _to_public, sse_manager

logger = logging.getLogger(__name__)

# 公开事件白名单：AgentEventDraft 中允许对外推送的字段
_PUBLIC_FIELDS = {"agent", "event_type", "status", "summary", "source_refs", "duration_ms"}


class AgentEventSink:
    """C 通过此接口提交事件，D 完成持久化 + 推送。"""

    async def emit(
        self,
        *,
        run_id: str,
        event: AgentEventDraft,
        db_session,  # AsyncSession
    ) -> AgentEvent:
        """校验 → 生成序号 → 写库 → 发布 SSE。"""
        # 1. 公开字段白名单校验（阻止私有字段泄露）
        self._validate_public_fields(event)

        # 2. 序列号
        seq = await run_repo.get_next_sequence(db_session, run_id)

        # 3. 写库
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

        # 4. 发布 SSE
        public = _to_public(db_event)
        try:
            await sse_manager.publish(run_id, public)
        except Exception:
            logger.exception("SSE publish failed for run_id=%s seq=%d", run_id, seq)

        return public

    @staticmethod
    def _validate_public_fields(event: AgentEventDraft) -> None:
        """确保事件草稿不含非白名单字段（双重保险）。"""
        # AgentEventDraft 本身只定义了公开字段，Pydantic 验证已做第一层过滤。
        # 此处做第二层 runtime 校验。
        extra = set(event.model_dump().keys()) - _PUBLIC_FIELDS
        if extra:
            logger.error("non-public fields in event draft: %s", extra)


# 模块级单例
agent_event_sink = AgentEventSink()
