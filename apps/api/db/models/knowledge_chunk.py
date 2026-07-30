"""知识块模型 — 检索最小单元"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = pk()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_from: Mapped[int] = mapped_column(Integer, nullable=False)
    page_to: Mapped[int] = mapped_column(Integer, nullable=False)
    question_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    section_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    private_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    material_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requires_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    embedding_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at = created_at_col()
