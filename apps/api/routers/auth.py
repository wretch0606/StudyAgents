"""认证 API 路由 — 登录/注销/当前用户/CSRF Token。

对齐前端 api(6).ts 契约：
  - POST /api/auth/login    → LoginResponse
  - GET  /api/auth/me       → UserInfo
  - POST /api/auth/logout   → LogoutResponse
  - GET  /api/auth/csrf-token → CsrfTokenResponse
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import get_session as get_db_session
from apps.api.dependencies.auth import (
    SESSION_COOKIE,
    invalidate_csrf,
    store_csrf_token,
)
from apps.api.repositories import auth as auth_repo
from apps.api.schemas.auth import (
    CsrfTokenResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserInfo,
)
from apps.api.schemas.error import ApiError
from apps.api.services.auth import (
    check_rate_limit,
    generate_session_token,
    hash_token,
    permissions_for_role,
    session_expires_at,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ============================================================
# POST /api/auth/login
# ============================================================

@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LoginResponse:
    """登录：校验凭据，创建会话，设置 Cookie，返回用户信息+CSRF Token。"""
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(body.username, client_ip)

    user = await auth_repo.find_user_by_username(session, body.username)
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(
            "AUTH_INVALID_CREDENTIALS", "用户名或密码错误。",
            status_code=401, retryable=False,
        )

    raw_token = generate_session_token()
    token_hash = hash_token(raw_token)
    expires = session_expires_at()
    client_info = request.headers.get("user-agent", "")
    await auth_repo.create_auth_session(session, user.id, token_hash, expires, client_info)

    csrf_token = store_csrf_token(token_hash)

    response.set_cookie(
        SESSION_COOKIE, raw_token,
        httponly=True, samesite="lax", secure=False,
        path="/api", max_age=8 * 3600,
    )

    return LoginResponse(
        user=UserInfo(
            id=str(user.id), username=user.username,
            display_name=user.display_name, role=user.role,
            permissions=permissions_for_role(user.role),
        ),
        csrf_token=csrf_token,
    )


# ============================================================
# GET /api/auth/me
# ============================================================

_SESSION_COOKIE_PARAM = Annotated[str | None, Cookie(alias="studyagents_session")]


@router.get("/me", response_model=UserInfo)
async def me(
    studyagents_session: _SESSION_COOKIE_PARAM = None,
    session: AsyncSession = Depends(get_db_session),
) -> UserInfo:
    """返回当前登录用户信息。页面刷新后前端调用此接口恢复会话。"""
    if not studyagents_session:
        raise ApiError(
            "AUTH_SESSION_EXPIRED", "会话已过期，请重新登录。",
            status_code=401, retryable=False,
        )

    token_hash = hash_token(studyagents_session)
    auth = await auth_repo.find_session_by_token_hash(session, token_hash)

    if auth is None or auth.revoked_at is not None:
        raise ApiError(
            "AUTH_SESSION_EXPIRED", "会话已过期，请重新登录。",
            status_code=401, retryable=False,
        )

    now = datetime.now(UTC).replace(tzinfo=None)
    if auth.expires_at < now:
        raise ApiError(
            "AUTH_SESSION_EXPIRED", "会话已过期，请重新登录。",
            status_code=401, retryable=False,
        )

    user = await auth_repo.find_user_by_id(session, auth.user_id)
    if user is None or not user.is_active:
        raise ApiError(
            "AUTH_SESSION_EXPIRED", "会话已过期，请重新登录。",
            status_code=401, retryable=False,
        )

    await auth_repo.touch_session(session, token_hash)

    return UserInfo(
        id=str(user.id), username=user.username,
        display_name=user.display_name, role=user.role,
        permissions=permissions_for_role(user.role),
    )


# ============================================================
# POST /api/auth/logout
# ============================================================

@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    studyagents_session: _SESSION_COOKIE_PARAM = None,
    session: AsyncSession = Depends(get_db_session),
) -> LogoutResponse:
    """注销：撤销会话，清除 Cookie，废止 CSRF Token。幂等成功。"""
    response.delete_cookie("studyagents_session", path="/api")

    if studyagents_session:
        token_hash = hash_token(studyagents_session)
        await auth_repo.revoke_session(session, token_hash)
        invalidate_csrf(token_hash)

    return LogoutResponse(success=True)


# ============================================================
# GET /api/auth/csrf-token
# ============================================================

@router.get("/csrf-token", response_model=CsrfTokenResponse)
async def csrf_token(
    studyagents_session: _SESSION_COOKIE_PARAM = None,
    session: AsyncSession = Depends(get_db_session),
) -> CsrfTokenResponse:
    """刷新 CSRF Token。前端页面刷新后调用此接口恢复 Token。"""
    if not studyagents_session:
        raise ApiError(
            "AUTH_SESSION_EXPIRED", "会话已过期，请重新登录。",
            status_code=401, retryable=False,
        )

    token_hash = hash_token(studyagents_session)
    auth = await auth_repo.find_session_by_token_hash(session, token_hash)

    if auth is None or auth.revoked_at is not None:
        raise ApiError(
            "AUTH_SESSION_EXPIRED", "会话已过期，请重新登录。",
            status_code=401, retryable=False,
        )

    return CsrfTokenResponse(csrf_token=store_csrf_token(token_hash))
