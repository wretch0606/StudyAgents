"""trace_id 中间件 — 为每个请求注入或提取 trace_id。

纯 ASGI 中间件，处理 trace_id 生命周期与未处理异常兜底。
"""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")

TRACE_HEADER = "X-Trace-Id"


def get_trace_id() -> str:
    """获取当前请求的 trace_id（从 ContextVar）。"""
    return _trace_id_ctx.get()


class TraceMiddleware:
    """纯 ASGI 中间件：trace_id + 响应头注入 + 未处理异常兜底。

    - 从请求头 X-Trace-Id 提取（ASGI scope 头为小写键），否则生成 UUID hex。
    - 所有 HTTP 响应头自动携带 X-Trace-Id。
    - 未处理异常（response 尚未开始发送时）返回统一的 INTERNAL_ERROR JSON。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 提取或生成 trace_id（ASGI scope headers 为小写字节键）
        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        headers_dict: dict[bytes, bytes] = dict(raw_headers)
        raw = headers_dict.get(TRACE_HEADER.lower().encode(), b"")
        trace_id = raw.decode() if raw else uuid.uuid4().hex
        _trace_id_ctx.set(trace_id)

        response_started = False

        async def _send(message: dict) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                existing = [v for k, v in headers if k.lower() == TRACE_HEADER.lower().encode()]
                if not existing:
                    headers.append((TRACE_HEADER.lower().encode(), trace_id.encode()))
                    message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            # 如果 FastAPI handler 已发送响应，不再重复发送
            if not response_started:
                logger.exception("unhandled exception caught by TraceMiddleware")
                body = json.dumps(
                    {
                        "code": "INTERNAL_ERROR",
                        "message": "服务器内部错误，请提供 trace_id 联系管理员。",
                        "retryable": True,
                        "trace_id": trace_id,
                        "details": None,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"application/json; charset=utf-8"),
                            (TRACE_HEADER.lower().encode(), trace_id.encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
            # 不重新抛出；响应已发送或已由此兜底。
