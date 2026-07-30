"""GradeResult — 评分结果，含各维度得分和复核状态。"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class GradeResult(Base):
    __tablename__ = "grade_results"

    id: Mapped[str] = pk()
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("answer_submissions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True,
    )
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 各维度得分（私有 — 仅 C 内部使用）
    step_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
    )  # pending | approved | rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    public_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = created_at_col()

    def __repr__(self) -> str:
        return (
            f"<GradeResult id={self.id} sub={self.submission_id} "
            f"score={self.total_score}>"
        )
