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

    def mark_completed(self, run_id: str) -> None:
        self._run_completed.add(run_id)

    def is_completed(self, run_id: str) -> bool:
        return run_id in self._run_completed

    async def sse_endpoint(
        self, run_id: str, request_headers: dict, *, user_id: str,
    ) -> StreamingResponse:
        """FastAPI 路由可直接返回的 SSE StreamingResponse。

        支持 Last-Event-ID 补发。user_id 用于属主隔离。
        """
        queue = await self.connect(run_id)

        async def event_generator():
            # 补发
            last_id = request_headers.get("last-event-id", "")
            if last_id:
                try:
                    since = int(last_id)
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
                    pass

            # 心跳 + 事件推送
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                        yield f"data: {msg}\n\n"
                    except TimeoutError:
                        yield ": heartbeat\n\n"

                    if self.is_completed(run_id) and queue.empty():
                        yield "event: run.completed\ndata: {}\n\n"
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
