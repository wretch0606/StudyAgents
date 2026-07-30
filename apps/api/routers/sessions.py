"""Chat Session REST API — 会话 CRUD + 问答启动 + 消息历史。

所有查询强制属主隔离；写操作执行 CSRF 校验。
"""

from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import get_current_user, require_csrf
from apps.api.schemas.chat import (
    CreateSessionRequest,
    MessageListResponse,
    MessageResponse,
    SessionListResponse,
    SessionResponse,
    StartQaRequest,
    StartQaResponse,
)
from apps.api.schemas.error import ApiError
from apps.api.services.chat import ChatService

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_to_response(s) -> SessionResponse:
    return SessionResponse(
        id=str(s.id),
        title=s.title,
        thread_id=str(s.thread_id),
        created_at=s.created_at.isoformat() if s.created_at else "",
        updated_at=s.updated_at.isoformat() if s.updated_at else "",
    )


def _msg_to_response(m) -> MessageResponse:
    return MessageResponse(
        id=str(m.id),
        role=m.role,
        content=m.content,
        run_id=str(m.run_id) if m.run_id else None,
        sequence_no=m.sequence_no,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


# ---- POST /api/sessions ----

@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    """创建新会话。"""
    svc = ChatService(session)
    sid = str(_uuid.uuid4())
    tid = body.thread_id or str(_uuid.uuid4())
    result = await svc.create_session(
        session_id=sid, user_id=user_id, thread_id=tid, title=body.title,
    )
    await session.commit()
    return _session_to_response(result)


# ---- GET /api/sessions ----

@router.get("", response_model=SessionListResponse)
async def list_sessions(
    user_id: str = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> SessionListResponse:
    """列出当前用户的所有会话（最新在前）。"""
    svc = ChatService(session)
    items = await svc.list_sessions(user_id=user_id, limit=limit, offset=offset)
    return SessionListResponse(
        items=[_session_to_response(s) for s in items],
        total=len(items),
    )


# ---- GET /api/sessions/{session_id} ----

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    """获取单个会话详情（属主隔离）。"""
    svc = ChatService(session)
    result = await svc.get_session(session_id=session_id, user_id=user_id)
    if result is None:
        raise ApiError(
            "RESOURCE_NOT_FOUND",
            "会话不存在。",
            status_code=404,
            retryable=False,
        )
    return _session_to_response(result)


# ---- POST /api/sessions/{session_id}/qa ----

@router.post("/{session_id}/qa", response_model=StartQaResponse, status_code=202)
async def start_qa(
    session_id: str,
    body: StartQaRequest,
    user_id: str = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> StartQaResponse:
    """发起问答 — 立即返回 run_id，后台异步执行。

    不等待模型结果；首个状态事件 P95 ≤ 2s。
    """
    # Verify session exists and belongs to user
    chat_svc = ChatService(session)
    chat_session = await chat_svc.get_session(
        session_id=session_id, user_id=user_id,
    )
    if chat_session is None:
        raise ApiError(
            "RESOURCE_NOT_FOUND",
            "会话不存在。",
            status_code=404,
            retryable=False,
        )

    # Check runner is initialized
    from apps.api.services.agent_runner import agent_runner_service

    if agent_runner_service is None:
        raise ApiError(
            "AGENT_DISPATCHER_NOT_CONFIGURED",
            "Agent 执行器尚未配置。",
            status_code=503,
            retryable=True,
        )

    # Start QA with session's thread_id
    result = await agent_runner_service.start_qa(
        session=session,
        session_id=session_id,
        user_id=user_id,
        user_input=body.user_input,
        mode=body.mode,
        thread_id=str(chat_session.thread_id),
    )

    return StartQaResponse(
        run_id=result["run_id"],
        thread_id=result["thread_id"],
        trace_id=result["trace_id"],
    )


# ---- GET /api/sessions/{session_id}/messages ----

@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def get_messages(
    session_id: str,
    user_id: str = Depends(get_current_user),
    since_seq: int = Query(-1, ge=-1),
    session: AsyncSession = Depends(get_db_session),
) -> MessageListResponse:
    """获取会话消息历史（属主隔离）。"""
    svc = ChatService(session)
    messages = await svc.get_messages(
        session_id=session_id, user_id=user_id, since_seq=since_seq,
    )
    return MessageListResponse(
        items=[_msg_to_response(m) for m in messages],
    )
