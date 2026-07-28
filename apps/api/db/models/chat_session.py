"""ChatSession model — groups messages for a user, links to an AgentRun via thread_id."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    thread_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    created_at = created_at_col()
    updated_at = updated_at_col()

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user_id={self.user_id}>"
