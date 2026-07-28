"""健康检查路由。"""

from __future__ import annotations

import logging

import psycopg
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from apps.api.config import settings
from apps.api.dependencies.trace import trace_id_dependency

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """存活检查 — 不依赖外部服务，仅验证进程存活。"""
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(trace_id: str = Depends(trace_id_dependency)) -> JSONResponse:
    """就绪检查 — 验证应用可处理请求且数据库可连通。

    数据库不可用时返回 503（degraded），不视为崩溃。
    """
    db_ok = False
    db_error: str | None = None

    if not settings.database_url:
        db_error = "DATABASE_URL not configured"
    else:
        try:
            # 去除 SQLAlchemy 驱动前缀，得到 psycopg 原生 URI
            native_url = settings.database_url.replace("+psycopg", "")
            conn = await psycopg.AsyncConnection.connect(
                native_url,
                autocommit=True,
                connect_timeout=5,
            )
            await conn.execute("SELECT 1")
            await conn.close()
            db_ok = True
        except Exception as exc:
            db_error = type(exc).__name__
            logger.warning(
                "database not ready: component=database type=%s error=%s trace_id=%s",
                type(exc).__name__, exc, trace_id,
            )

    payload = {
        "status": "ok" if db_ok else "degraded",
        "trace_id": trace_id,
        "database": {
            "connected": db_ok,
            "error": db_error,
        },
    }

    http_status = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=payload, status_code=http_status)
