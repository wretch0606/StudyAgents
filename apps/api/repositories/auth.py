"""认证仓储 — 用户查询、会话持久化。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.auth_session import AuthSession
from apps.api.db.models.user import User


async def find_user_by_username(session: AsyncSession, username: str) -> User | None:
    """按用户名查找活跃用户。"""
    result = await session.execute(
        select(User).where(User.username == username, User.is_active)
    )
    return result.scalar_one_or_none()


async def find_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    """按 ID 查找用户。"""
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def find_session_by_token_hash(
    session: AsyncSession, token_hash: str
) -> AuthSession | None:
    """按令牌哈希查找会话。"""
    result = await session.execute(
        select(AuthSession).where(AuthSession.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def create_auth_session(
    session: AsyncSession,
    user_id: str,
    token_hash: str,
    expires_at: datetime,
    client_info: str | None = None,
) -> AuthSession:
    """创建新的认证会话记录。"""
    auth = AuthSession(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        client_info=client_info,
    )
    session.add(auth)
    await session.flush()
    return auth


async def revoke_session(session: AsyncSession, token_hash: str) -> bool:
    """撤销会话（设置 revoked_at）。返回是否找到并撤销。"""
    auth = await find_session_by_token_hash(session, token_hash)
    if auth is None:
        return False
    auth.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    return True


async def touch_session(session: AsyncSession, token_hash: str) -> None:
    """更新会话的最后使用时间。"""
    auth = await find_session_by_token_hash(session, token_hash)
    if auth:
        auth.last_used_at = datetime.now(UTC).replace(tzinfo=None)
        await session.flush()
