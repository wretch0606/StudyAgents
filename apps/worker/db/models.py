"""
SQLAlchemy ORM 模型 — 成员 B 负责的表

documents, document_pages, knowledge_chunks, knowledge_points,
chunk_knowledge_points, exam_questions, ingestion_jobs, review_items

注意：向量维度由嵌入模型决定，此处使用默认值；实际部署时应通过 Alembic
迁移动态适配。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# 文档与页面
# ============================================================

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name = Column(String(255), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    mime = Column(String(127), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_path = Column(String(1024), nullable=False)  # 相对路径
    status = Column(String(16), nullable=False, default="importing")
    version = Column(Integer, nullable=False, default=1)
    active = Column(Boolean, nullable=False, default=False)
    metadata_ = Column("metadata", JSONB, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")
    exam_questions = relationship("ExamQuestion", back_populates="document", cascade="all, delete-orphan")
    ingestion_jobs = relationship("IngestionJob", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "ix_documents_sha256_active",
            "sha256",
            "active",
            unique=True,
            postgresql_where=text("active = true"),
        ),
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_no = Column(Integer, nullable=False)
    raw_text = Column(Text, nullable=True)
    image_path = Column(String(1024), nullable=True)
    char_count = Column(Integer, nullable=False, default=0)
    text_coverage = Column(Float, nullable=True)
    page_type = Column(String(16), nullable=True)  # digital | scanned | mixed
    layout_json = Column(JSONB, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    document = relationship("Document", back_populates="pages")

    __table_args__ = (UniqueConstraint("document_id", "page_no"),)


# ============================================================
# 知识块
# ============================================================

class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_from = Column(Integer, nullable=False)
    page_to = Column(Integer, nullable=False)
    question_no = Column(String(32), nullable=True)
    section_path = Column(String(512), nullable=True)
    content = Column(Text, nullable=False)
    private_content = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=False)
    visibility = Column(String(16), nullable=False, default="public")
    material_type = Column(String(32), nullable=True)
    year = Column(Integer, nullable=True)
    image_refs = Column(JSONB, nullable=True)
    requires_vision = Column(Boolean, nullable=False, default=False)
    embedding_version = Column(String(64), nullable=True)
    document_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    document = relationship("Document", back_populates="chunks")
    chunk_kp = relationship("ChunkKnowledgePoint", back_populates="chunk", cascade="all, delete-orphan")

    # 注意：vector 和 search_vector 列需通过 Alembic raw SQL 添加：
    # ALTER TABLE knowledge_chunks ADD COLUMN vector vector(1536);
    # ALTER TABLE knowledge_chunks ADD COLUMN search_vector tsvector;
    # CREATE INDEX ON knowledge_chunks USING hnsw (vector vector_cosine_ops)
    #   WITH (m = 16, ef_construction = 200);
    # CREATE INDEX ON knowledge_chunks USING gin (search_vector);


# ============================================================
# 知识点
# ============================================================

class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    code = Column(String(64), nullable=False, unique=True)  # "CH3.2.1"
    name = Column(String(255), nullable=False)
    chapter = Column(String(128), nullable=True)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_points.id"), nullable=True)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)

    children = relationship("KnowledgePoint", backref="parent", remote_side="KnowledgePoint.id")


class ChunkKnowledgePoint(Base):
    __tablename__ = "chunk_knowledge_points"

    chunk_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_point_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        primary_key=True,
    )
    confidence = Column(Float, nullable=False, default=1.0)

    chunk = relationship("KnowledgeChunk", back_populates="chunk_kp")
    knowledge_point = relationship("KnowledgePoint")


# ============================================================
# 真题
# ============================================================

class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    question_no = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    question_type = Column(String(32), nullable=False)
    stem = Column(Text, nullable=False)
    options = Column(JSONB, nullable=True)
    score = Column(Float, nullable=True)
    difficulty = Column(Integer, nullable=True)
    answer_private = Column(Text, nullable=True)
    rubric_private = Column(JSONB, nullable=True)
    answer_origin = Column(String(32), nullable=True)  # original | ai_reviewed
    answer_confidence = Column(Float, nullable=True)
    page_no = Column(Integer, nullable=False)
    knowledge_point_ids = Column(JSONB, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    document = relationship("Document", back_populates="exam_questions")

    __table_args__ = (UniqueConstraint("document_id", "question_no", "version"),)


# ============================================================
# 导入任务
# ============================================================

class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(32), nullable=False, default="validating")
    status = Column(String(16), nullable=False, default="pending")
    progress = Column(Float, nullable=False, default=0.0)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    lease_holder = Column(String(64), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    error_summary = Column(Text, nullable=True)
    error_detail = Column(JSONB, nullable=True)
    trace_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    document = relationship("Document", back_populates="ingestion_jobs")

    __table_args__ = (
        Index("ix_ingestion_jobs_status", "status"),
    )


# ============================================================
# 复核
# ============================================================

class ReviewItem(Base):
    __tablename__ = "review_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    kind = Column(String(32), nullable=False)  # ocr_formula | ocr_text | missing_answer | low_confidence
    target_type = Column(String(32), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    confidence = Column(Float, nullable=False)
    page_no = Column(Integer, nullable=True)
    payload = Column(JSONB, nullable=False)
    correction = Column(JSONB, nullable=True)
    status = Column(String(16), nullable=False, default="pending")  # pending | resolved | dismissed
    reviewer_id = Column(UUID(as_uuid=True), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_review_items_status_kind", "status", "kind"),)
