"""AnswerSubmission — 用户原始答案提交。

一次提交唯一约束 (item_id, attempt)，支持幂等返回原结果。
"""

from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class AnswerSubmission(Base):
    __tablename__ = "answer_submissions"
    __table_args__ = (
        UniqueConstraint("item_id", "attempt", name="uq_answer_submissions_item_attempt"),
    )

    id: Mapped[str] = pk()
    item_id: Mapped[str] = mapped_column(
        ForeignKey("practice_items.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    created_at = created_at_col()

    def __repr__(self) -> str:
        return f"<AnswerSubmission id={self.id} item={self.item_id} attempt={self.attempt}>"
