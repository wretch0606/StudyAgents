"""PracticeSession — 训练会话，分组用户的练习题目。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    thread_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active",
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="practice")
    created_at = created_at_col()
    updated_at = updated_at_col()

    def __repr__(self) -> str:
        return f"<PracticeSession id={self.id} user_id={self.user_id}>"
