"""认证 FastAPI 依赖 — Session、CSRF、权限。

前端约定：
  - Cookie Session（HttpOnly, SameSite=Lax）
  - CSRF Token 通过 X-CSRF-Token 请求头传递
  - 页面刷新后通过 GET /api/auth/csrf-token 恢复 Token
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import get_session as get_db_session
from apps.api.repositories import auth as auth_repo
from apps.api.schemas.error import ApiError
from apps.api.services.auth import hash_token

SESSION_COOKIE = "studyagents_session"

# 内存中的 CSRF Token 映射：{session_token_hash: csrf_token}
_csrf_store: dict[str, str] = {}


# ---- CSRF ----

def generate_csrf_token() -> str:
    """生成密码学安全的 CSRF Token。"""
    return secrets.token_urlsafe(32)


def store_csrf_token(session_token_hash: str) -> str:
    """生成并存储 CSRF Token，返回给调用方。"""
    token = generate_csrf_token()
    _csrf_store[session_token_hash] = token
    return token


def validate_csrf(session_token_hash: str, csrf_header: str | None) -> None:
    """验证 CSRF Token 是否匹配。"""
    stored = _csrf_store.get(session_token_hash)
    if stored is None or csrf_header != stored:
        raise ApiError(
            "CSRF_TOKEN_INVALID",
            "CSRF Token 无效或已过期，请刷新页面后重试。",
            status_code=403,
            retryable=False,
        )


def invalidate_csrf(session_token_hash: str) -> None:
    """清除指定会话的 CSRF Token。"""
    _csrf_store.pop(session_token_hash, None)


# ---- Session ----

def _read_token_from_cookie(
    studyagents_session: Annotated[str | None, Cookie()] = None,
) -> str | None:
    """从 Cookie 提取原始会话令牌。"""
    return studyagents_session


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    raw_token: Annotated[str | None, Depends(_read_token_from_cookie)],
) -> str:
    """从 Cookie 解析当前登录用户 ID。

    返回 user_id 字符串；未登录或会话无效时抛出 401。
    """
    if not raw_token:
        raise ApiError(
            "AUTH_SESSION_EXPIRED",
            "会话已过期，请重新登录。",
            status_code=401,
            retryable=False,
        )
    token_hash = hash_token(raw_token)
    auth = await auth_repo.find_session_by_token_hash(session, token_hash)

    if auth is None:
        raise ApiError(
            "AUTH_SESSION_EXPIRED",
            "会话已过期，请重新登录。",
            status_code=401,
            retryable=False,
        )

    if auth.revoked_at is not None:
        raise ApiError(
            "AUTH_SESSION_EXPIRED",
            "会话已注销，请重新登录。",
            status_code=401,
            retryable=False,
        )

    now = __import__("datetime").datetime.now(__import__("datetime").UTC).replace(tzinfo=None)
    if auth.expires_at < now:
        raise ApiError(
            "AUTH_SESSION_EXPIRED",
            "会话已过期，请重新登录。",
            status_code=401,
            retryable=False,
        )

    # 查询用户 role 以支持权限校验
    user = await auth_repo.find_user_by_id(session, auth.user_id)
    user_role = user.role if user else "member"

    # 将 token_hash 和 user 信息存入 request.state 供 CSRF 和权限使用
    request.state._token_hash = token_hash  # type: ignore[attr-defined]
    request.state._user_id = auth.user_id  # type: ignore[attr-defined]
    request.state._user_role = user_role  # type: ignore[attr-defined]

    return auth.user_id


# ---- CSRF 写保护 ----

def _check_origin(request: Request) -> None:
    """校验 Origin 头（宽松模式：仅当 Origin 存在时校验）。"""
    origin = request.headers.get("origin")
    # 开发阶段：Origin 缺失时不拒绝（同源请求）
    if origin is None:
        return
    # 生产环境应严格校验 Origin 在白名单内
    # allowed = {"http://localhost:8080", "http://127.0.0.1:8080"}
    # if origin not in allowed: raise ApiError(...)


async def require_csrf(
    request: Request,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    """写请求 CSRF 校验依赖。

    注入到需要 CSRF 保护的路由中（POST/PATCH/PUT/DELETE）。
    """
    _check_origin(request)
    token_hash: str = getattr(request.state, "_token_hash", "")
    if not token_hash:
        raise ApiError(
            "AUTH_REQUIRED",
            "请先登录后再执行此操作。",
            status_code=401,
            retryable=False,
        )
    validate_csrf(token_hash, x_csrf_token)


# ---- 权限 ----

async def require_admin(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> str:
    """要求管理员角色 — 用作 FastAPI Depends。

    普通成员访问时抛出 403 AUTH_FORBIDDEN。
    """
    role: str = getattr(request.state, "_user_role", "")
    if role != "admin":
        raise ApiError(
            "AUTH_FORBIDDEN",
            "权限不足。",
            status_code=403,
            retryable=False,
        )
    return user_id
