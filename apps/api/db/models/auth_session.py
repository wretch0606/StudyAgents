"""认证会话表 — 数据库仅保存令牌哈希，不保存浏览器原始令牌。"""

from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at = created_at_col()
    expires_at: Mapped[str] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[str] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[str] = mapped_column(DateTime, nullable=True)
    client_info: Mapped[str] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:
        return f"<AuthSession id={self.id} user_id={self.user_id}>"
