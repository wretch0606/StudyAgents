"""幂等记录表 — 按 (user_id, scope, idempotency_key) 唯一定位。

用于上传、作答提交等关键写请求的去重与重放安全。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "scope", "idempotency_key",
            name="uq_idempotency_user_scope_key",
        ),
    )

    id: Mapped[str] = pk()
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending | processing | completed | failed
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at = created_at_col()
    updated_at = updated_at_col()

    def __repr__(self) -> str:
        return (
            f"<IdempotencyRecord user={self.user_id} "
            f"scope={self.scope} key={self.idempotency_key}>"
        )
