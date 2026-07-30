"""ChatMessage model — individual user/assistant messages within a chat session.

Partial unique index enforces write-once idempotency for assistant answers:
at most one assistant message per run_id.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index(
            "uq_chat_messages_assistant_run",
            "run_id",
            unique=True,
            postgresql_where=sa_text("role = 'assistant' AND run_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = pk()
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at = created_at_col()

    def __repr__(self) -> str:
        return (
            f"<ChatMessage id={self.id} session={self.session_id} "
            f"role={self.role} seq={self.sequence_no}>"
        )
