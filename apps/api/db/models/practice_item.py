"""PracticeItem — 题目快照，公开与私有答案分层保存。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class PracticeItem(Base):
    __tablename__ = "practice_items"
    __table_args__ = (
        UniqueConstraint("session_id", "order_no", name="uq_practice_items_session_order"),
    )

    id: Mapped[str] = pk()
    session_id: Mapped[str] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True,
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="generated",
    )
    source_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    question_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1.0",
    )
    # 公开快照：冻结的 PublicQuestion（不含答案/评分标准）
    public_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 私有快照：冻结的答案/评分标准（仅 C 内部使用，不通过 API 暴露）
    private_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at = created_at_col()

    def __repr__(self) -> str:
        return f"<PracticeItem id={self.id} session={self.session_id} order={self.order_no}>"
