"""Agent 运行记录表 — 每次问答/训练步骤对应一次 Run。"""

from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = pk()
    thread_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # qa | practice
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued"
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=True)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    node_hops: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_cny: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[str] = mapped_column(DateTime, nullable=True)
    created_at = created_at_col()

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} mode={self.mode} status={self.status}>"
