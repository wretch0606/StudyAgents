"""MasteryChangeLog — 掌握度变更审计日志。

每次变更记录 before/after/reason/source_grade_id。
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class MasteryChangeLog(Base):
    __tablename__ = "mastery_change_logs"

    id: Mapped[str] = pk()
    mastery_id: Mapped[str] = mapped_column(
        ForeignKey("mastery_records.id", ondelete="CASCADE"), nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    change_reason: Mapped[str] = mapped_column(String(128), nullable=False)
    source_grade_id: Mapped[str | None] = mapped_column(
        ForeignKey("grade_results.id", ondelete="SET NULL"), nullable=True,
    )
    before_level: Mapped[float] = mapped_column(Float, nullable=False)
    after_level: Mapped[float] = mapped_column(Float, nullable=False)
    before_streak: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_streak: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at = created_at_col()

    def __repr__(self) -> str:
        return (
            f"<MasteryChangeLog id={self.id} "
            f"{self.before_level}→{self.after_level} reason={self.change_reason}>"
        )
