"""Agent 事件表 — SSE 推送前先持久化，保证断线可续传。

事件按 (run_id, sequence_no) 唯一约束，sequence_no 在单次 Run 内严格递增。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_no", name="uq_agent_events_run_seq"),
    )

    id: Mapped[str] = pk()
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_refs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    private_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at = created_at_col()

    def __repr__(self) -> str:
        return f"<AgentEvent run={self.run_id} seq={self.sequence_no} agent={self.agent}>"
