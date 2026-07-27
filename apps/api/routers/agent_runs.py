"""Agent Run API 路由 — GET run / GET events (SSE) / POST retry。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user
from apps.api.repositories import agent_run as run_repo
from apps.api.schemas.agent import AgentRunSummary, RetryAgentRunResponse
from apps.api.schemas.error import ApiError
from apps.api.services.sse_manager import sse_manager

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])

# 可重试状态
RETRYABLE_STATUSES = {"failed", "cancelled"}


def _check_owner(run, user_id: str) -> None:
    """非管理员只能访问自己的 Run。"""
    # admin 可以访问所有 Run
    if str(run.user_id) != user_id:
        raise ApiError("AUTH_FORBIDDEN", "无权访问此 Agent Run。", status_code=403, retryable=False)


# ---- GET /api/agent-runs/{run_id} ----

@router.get("/{run_id}", response_model=AgentRunSummary)
async def get_agent_run(
    run_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AgentRunSummary:
    run = await run_repo.get_run(session, run_id, user_id=user_id)
    if run is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Run 不存在。", status_code=404, retryable=False)
    _check_owner(run, user_id)
    return AgentRunSummary(
        id=str(run.id), thread_id=str(run.thread_id), mode=run.mode, status=run.status,
        model=run.model, model_calls=run.model_calls, node_hops=run.node_hops,
        input_tokens=run.input_tokens, output_tokens=run.output_tokens,
        estimated_cost_cny=run.estimated_cost_cny, error=run.error,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        created_at=run.created_at.isoformat() if run.created_at else "",
    )


# ---- GET /api/agent-runs/{run_id}/events (SSE) ----

@router.get("/{run_id}/events")
async def get_agent_run_events(
    run_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    run = await run_repo.get_run(session, run_id, user_id=user_id)
    if run is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Run 不存在。", status_code=404, retryable=False)
    _check_owner(run, user_id)
    headers = {k.lower(): v for k, v in request.headers.items()}
    return await sse_manager.sse_endpoint(run_id, headers, user_id=user_id)


# ---- POST /api/agent-runs/{run_id}/retry ----

@router.post("/{run_id}/retry", response_model=RetryAgentRunResponse)
async def retry_agent_run(
    run_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RetryAgentRunResponse:
    run = await run_repo.get_run(session, run_id, user_id=user_id)
    if run is None:
        raise ApiError("RESOURCE_NOT_FOUND", "Run 不存在。", status_code=404, retryable=False)
    _check_owner(run, user_id)

    if run.status not in RETRYABLE_STATUSES:
        raise ApiError(
            "AGENT_LIMIT_EXCEEDED",
            f"Run 状态为 {run.status}，不可重试。仅 {', '.join(RETRYABLE_STATUSES)} 状态可重试。",
            status_code=422,
            retryable=False,
        )

    # 通过 AgentRunnerService 重试
    from apps.api.services.agent_runner import (
        AgentRunnerError,
        agent_runner_service,
    )

    if agent_runner_service is None:
        raise ApiError(
            "AGENT_DISPATCHER_NOT_CONFIGURED",
            "Agent 执行器尚未配置，无法重试。请调用 init_agent_runner() 初始化。",
            status_code=503,
            retryable=True,
        )

    try:
        result = await agent_runner_service.retry_run(
            run_id=run_id, user_id=user_id, session=session,
        )
        return RetryAgentRunResponse(
            run=AgentRunSummary(
                id=str(run.id),
                thread_id=str(run.thread_id),
                mode=run.mode,
                status=result["status"],
                model=run.model,
                model_calls=run.model_calls,
                node_hops=run.node_hops,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                estimated_cost_cny=run.estimated_cost_cny,
                error=run.error,
                started_at=run.started_at.isoformat() if run.started_at else None,
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
                created_at=run.created_at.isoformat() if run.created_at else "",
            ),
            event_url=result["event_url"],
        )
    except AgentRunnerError as exc:
        raise ApiError(
            exc.code, exc.message,
            status_code=exc.status_code, retryable=exc.retryable,
        ) from exc
