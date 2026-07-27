"""认证请求/响应 Pydantic 模型 — 对齐前端 api(6).ts 契约。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """POST /api/auth/login 请求体。"""
    username: str
    password: str


class UserInfo(BaseModel):
    """用户公开信息（不放敏感字段）。"""
    id: str
    username: str
    display_name: str
    role: str
    permissions: list[str] = Field(default_factory=list)


class LoginResponse(BaseModel):
    """POST /api/auth/login 成功响应。"""
    user: UserInfo
    csrf_token: str


class CsrfTokenResponse(BaseModel):
    """GET /api/auth/csrf-token 响应。"""
    csrf_token: str


class LogoutResponse(BaseModel):
    """POST /api/auth/logout 响应。"""
    success: bool = True
