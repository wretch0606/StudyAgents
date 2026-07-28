"""认证服务 — 密码哈希、会话管理、登录限速。

- 密码：Argon2id
- 会话令牌：secrets.token_urlsafe(32)，数据库只存 SHA-256 哈希
- 默认会话过期：8 小时
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

SESSION_TTL_HOURS = 8

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

# 登录限速：{key: [attempt_timestamps]}
_rate_store: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
RATE_WINDOW_SECONDS = 300


# ---- 密码 ----

def hash_password(password: str) -> str:
    """使用 Argon2id 哈希密码。"""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码是否匹配。返回 True/False，不泄露原因。"""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# ---- 登录限速 ----

def check_rate_limit(username: str, client_ip: str) -> None:
    """检查账号+IP 登录限速。"""
    from apps.api.schemas.error import ApiError

    now = time.time()
    window_start = now - RATE_WINDOW_SECONDS

    for key in (f"user:{username}", f"ip:{client_ip}"):
        attempts = [t for t in _rate_store.get(key, []) if t > window_start]
        if len(attempts) >= MAX_LOGIN_ATTEMPTS:
            raise ApiError(
                "AUTH_RATE_LIMITED",
                "登录尝试次数过多，请稍后再试。",
                status_code=429,
                retryable=True,
            )
        _rate_store.setdefault(key, []).append(now)


# ---- 会话 ----

def generate_session_token() -> str:
    """生成密码学安全的随机会话令牌。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """对令牌做 SHA-256 哈希（数据库只存哈希）。"""
    return hashlib.sha256(token.encode()).hexdigest()


def session_expires_at() -> datetime:
    """返回会话过期时间（UTC naive）。"""
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=SESSION_TTL_HOURS)


# ---- 权限 ----

_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "member": ["qa:read", "practice:write", "learning:read"],
    "admin": [
        "qa:read", "practice:write", "learning:read",
        "kb:manage", "review:manage", "admin:access",
    ],
}


def permissions_for_role(role: str) -> list[str]:
    """返回角色对应的权限列表。"""
    return _ROLE_PERMISSIONS.get(role, [])
