"""文档页面模型 — 解析后每页的文本与页图"""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, created_at_col, pk


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[str] = pk()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    layout_json: Mapped[dict | None] = mapped_column("layout", JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at = created_at_col()
