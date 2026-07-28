"""WrongBookEntry — 错题本条目，记录错误答案和复习次数。"""

from __future__ import annotations

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col


class WrongBookEntry(Base):
    __tablename__ = "wrong_book_entries"

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("practice_items.id", ondelete="CASCADE"), nullable=False,
    )
    submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("answer_submissions.id", ondelete="SET NULL"), nullable=True,
    )
    grade_id: Mapped[str | None] = mapped_column(
        ForeignKey("grade_results.id", ondelete="SET NULL"), nullable=True,
    )
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stem_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    wrong_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_reviewed_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    # Issue 16-5 新增字段 — 对齐 api(6).ts WrongBookEntry 契约
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    knowledge_point_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    first_error_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    last_error_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_review_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = created_at_col()
    updated_at = updated_at_col()

    def __repr__(self) -> str:
        return f"<WrongBookEntry id={self.id} user={self.user_id} type={self.question_type}>"
