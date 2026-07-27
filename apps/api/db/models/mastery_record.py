"""MasteryRecord — 知识点掌握度记录，含连续正确次数。"""

from __future__ import annotations

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col


class MasteryRecord(Base):
    __tablename__ = "mastery_records"
    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_point", name="uq_mastery_user_kp"),
    )

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    knowledge_point: Mapped[str] = mapped_column(
        String(256), nullable=False,
    )
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_level: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
    )
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_practiced_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    created_at = created_at_col()
    updated_at = updated_at_col()

    def __repr__(self) -> str:
        return f"<MasteryRecord id={self.id} kp={self.knowledge_point} level={self.current_level}>"
