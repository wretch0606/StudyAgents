"""FastAPI 应用入口。

启动命令：`uv run uvicorn apps.api.main:app --reload`
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from apps.api.config import settings
from apps.api.middleware.logging import setup_logging
from apps.api.middleware.trace import TraceMiddleware, get_trace_id
from apps.api.routers import admin, auth, health
from apps.api.schemas.error import ApiError, ApiErrorResponse


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用（工厂函数，测试可复用）。"""
    # ---- 日志 ----
    setup_logging()
    logger = logging.getLogger(__name__)

    # ---- 应用实例 ----
    app = FastAPI(
        title="StudyAgents API",
        version="0.1.0",
        docs_url="/api/docs" if settings.app_env == "development" else None,
        redoc_url=None,
    )

    # ---- 中间件 ----
    app.add_middleware(TraceMiddleware)

    # ---- 路由 ----
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    # ---- 异常处理 ----
    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        """将 ApiError 转为统一错误响应格式。"""
        trace_id = get_trace_id()
        logger.warning(
            "api error code=%s status=%d retryable=%s",
            exc.code,
            exc.status_code,
            exc.retryable,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiErrorResponse(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                trace_id=trace_id,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        """捕获未处理异常，不向客户端返回堆栈。"""
        trace_id = get_trace_id()
        logger.exception(
            "unhandled exception",
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ApiErrorResponse(
                code="INTERNAL_ERROR",
                message="服务器内部错误，请提供 trace_id 联系管理员。",
                retryable=True,
                trace_id=trace_id,
                details=None,
            ).model_dump(),
        )

    return app


# 模块级单例 — 供 uvicorn 直接导入。
app = create_app()
