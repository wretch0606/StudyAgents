"""导入任务模型 — Worker 任务状态持久化。

Issue #11：完整状态机、租约、自动重试、恢复。
"""

from __future__ import annotations

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col

# 合法状态
VALID_STATUSES = {"pending", "running", "succeeded", "failed_retryable", "failed_permanent"}

# 合法阶段
VALID_STAGES = {
    "validate", "extract", "ocr", "structure", "chunk", "embed", "index", "complete",
}

# 最大重试次数（不含首次执行）
MAX_RETRIES = 2


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = pk()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="validate")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # 已尝试次数（含当前）
    lease_until: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(DateTime, nullable=True)
    created_at = created_at_col()
    updated_at = updated_at_col()

    @property
    def retry_count(self) -> int:
        """已重试次数 = attempts - 1（首次不算重试）。"""
        return max(0, (self.attempts or 0) - 1)

    @property
    def max_retries_reached(self) -> bool:
        return self.retry_count >= MAX_RETRIES

    def __repr__(self) -> str:
        return f"<IngestionJob id={self.id} doc={self.document_id} status={self.status}>"

