"""SSE 连接管理器 — 管理在线客户端、推送事件、心跳、断线清理。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from starlette.responses import StreamingResponse

from apps.api.schemas.agent import AgentEvent

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15.0  # 秒


class SSEManager:
    """管理多个 run 的 SSE 连接。

    每个 run 可有多个在线客户端（不同 tab/设备）。
    """

    def __init__(self) -> None:
        # run_id → list of asyncio.Queue
        self._queues: dict[str, list[asyncio.Queue[str]]] = defaultdict(list)
        self._run_completed: set[str] = set()

    async def connect(self, run_id: str) -> asyncio.Queue[str]:
        """注册新的 SSE 客户端，返回其消息队列。"""
        q: asyncio.Queue[str] = asyncio.Queue()
        self._queues[run_id].append(q)
        return q

    def disconnect(self, run_id: str, queue: asyncio.Queue[str]) -> None:
        """移除客户端队列。"""
        queues = self._queues.get(run_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._queues.pop(run_id, None)

    async def publish(self, run_id: str, event: AgentEvent) -> None:
        """向所有在线客户端推送事件。"""
        payload = json.dumps(event.model_dump(), ensure_ascii=False)
        for q in self._queues.get(run_id, []):
            await q.put(payload)

    def mark_completed(self, run_id: str, *, event_type: str = "run.completed") -> None:
        """标记 run 终止状态。event_type: 'run.completed' 或 'run.failed'。"""
        self._run_completed.add(run_id)
        self._run_terminal_event = getattr(self, "_run_terminal_event", {})
        self._run_terminal_event[run_id] = event_type

    def is_completed(self, run_id: str) -> bool:
        return run_id in self._run_completed

    def _get_terminal_event_type(self, run_id: str) -> str:
        """获取 run 的终止事件类型，默认为 run.completed。"""
        terminal = getattr(self, "_run_terminal_event", {})
        return terminal.get(run_id, "run.completed")

    async def sse_endpoint(
        self, run_id: str, request_headers: dict, *, user_id: str,
    ) -> StreamingResponse:
        """FastAPI 路由可直接返回的 SSE StreamingResponse。

        支持 Last-Event-ID 补发。user_id 用于属主隔离。
        """
        queue = await self.connect(run_id)

        async def event_generator():
            # 总是从数据库读取历史事件（fresh connect: since_seq=-1；reconnect: Last-Event-ID）
            last_id = request_headers.get("last-event-id", "")
            since = int(last_id) if last_id else -1
            try:
                from apps.api.db.session import _get_sessionmaker
                from apps.api.repositories.agent_run import get_events_since
                async with _get_sessionmaker()() as session:
                    events = await get_events_since(
                        session, run_id, user_id=user_id, since_seq=since,
                    )
                    for evt in events:
                        pub = _to_public(evt)
                        msg = json.dumps(pub.model_dump(), ensure_ascii=False)
                        yield f"id: {pub.sequence_no}\ndata: {msg}\n\n"
            except Exception:
                logger.exception("SSE history replay failed for run_id=%s", run_id)

            # DB 回退检查：如果 run 在数据库中已是终态但 _run_completed 未标记
            # （晚订阅、服务重启、或 practice_grade 等直接创建 completed run 的场景）
            if not self.is_completed(run_id):
                try:
                    from apps.api.db.session import _get_sessionmaker
                    from apps.api.repositories.agent_run import get_run
                    async with _get_sessionmaker()() as db_session:
                        db_run = await get_run(db_session, run_id, user_id=user_id)
                        if db_run is not None and db_run.status in (
                            "completed", "failed", "cancelled",
                        ):
                            terminal = (
                                "run.failed" if db_run.status == "failed"
                                else "run.completed"
                            )
                            self.mark_completed(run_id, event_type=terminal)
                except Exception:
                    logger.exception(
                        "SSE DB fallback check failed for run_id=%s", run_id,
                    )

            # 心跳 + 事件推送
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(
                            queue.get(), timeout=HEARTBEAT_INTERVAL,
                        )
                        yield f"data: {msg}\n\n"
                    except TimeoutError:
                        yield ": heartbeat\n\n"

                    if self.is_completed(run_id) and queue.empty():
                        terminal_type = self._get_terminal_event_type(run_id)
                        yield f"event: {terminal_type}\ndata: {{}}\n\n"
                        break
            except asyncio.CancelledError:
                pass
            finally:
                self.disconnect(run_id, queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


def _to_public(db_event) -> AgentEvent:
    """将数据库 AgentEvent 模型转为公开 DTO（白名单过滤）。"""
    return AgentEvent(
        id=str(db_event.id),
        run_id=str(db_event.run_id),
        sequence_no=db_event.sequence_no,
        agent=db_event.agent,
        event_type=db_event.event_type,
        status=db_event.status,
        summary=db_event.summary,
        source_refs=db_event.source_refs or [],
        duration_ms=db_event.duration_ms,
        created_at=db_event.created_at.isoformat() if db_event.created_at else "",
    )


# 模块级单例
sse_manager = SSEManager()
