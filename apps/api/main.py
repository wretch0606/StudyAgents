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
from apps.api.routers import (
    admin,
    agent_runs,
    auth,
    documents,
    grading,
    health,
    learning_summary,
    practice,
    sessions,
    training,
    wrong_book,
)
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
    app.include_router(agent_runs.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(documents.job_router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(practice.router, prefix="/api")  # 正式契约：/api/practice/sessions
    app.include_router(training.router, prefix="/api")  # 兼容旧路径 /api/training
    app.include_router(grading.router, prefix="/api")  # 兼容旧路径 /api/training/{id}/submit
    app.include_router(wrong_book.router, prefix="/api")
    app.include_router(learning_summary.router, prefix="/api")

    # ---- 初始化 Checkpointer（LangGraph 检查点持久化） ----
    from apps.api.services.checkpointer import init_checkpointer

    init_checkpointer()

    # ---- 初始化 AgentRunnerService ----
    from apps.api.services.agent_event_sink import agent_event_sink
    from apps.api.services.agent_runner import init_agent_runner

    # 根据环境选择真实或 Fake 组件
    if settings.app_env in ("production", "staging") or settings.model_api_key:
        # 生产环境或有 API Key → 使用真实组件
        from apps.api.services.model_gateway import OpenAIAdapter
        from apps.api.services.real_agent_runner import LangGraphAgentRunner

        logger.info("Using real ModelGateway (OpenAIAdapter) + LangGraphAgentRunner")
        init_agent_runner(
            runner=LangGraphAgentRunner(),
            model_gateway=OpenAIAdapter(),
            event_sink=agent_event_sink,
        )
    else:
        # 开发/测试环境无 API Key → 使用 Fake 组件
        logger.warning(
            "Using FakeAgentRunner + FakeAdapter — set MODEL_API_KEY for real AI"
        )
        init_agent_runner(
            runner=None,  # None → FakeAgentRunner
            model_gateway=None,  # None → FakeAdapter
            event_sink=agent_event_sink,
        )

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
