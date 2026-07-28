"""文档模型 — 资料上传后的主记录。

Issue #8 最小实现：不含 page/chunk 子表（由 B 后续扩展）。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk, updated_at_col


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at = created_at_col()
    updated_at = updated_at_col()

    def __repr__(self) -> str:
        return f"<Document id={self.id} name={self.name!r} status={self.status}>"
