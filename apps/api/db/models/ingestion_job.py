"""导入任务模型 — Worker 任务状态持久化。

Issue #8 最小实现：pending/running/succeeded/failed 状态流转。
租约、自动重试、恢复、死信 → Issue #11。
"""

from __future__ import annotations

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = pk()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="validate")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending | running | succeeded | failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    created_at = created_at_col()
    updated_at = updated_at_col()

    def __repr__(self) -> str:
        return f"<IngestionJob id={self.id} doc={self.document_id} status={self.status}>"
