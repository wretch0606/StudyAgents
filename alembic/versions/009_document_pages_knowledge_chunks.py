"""add document_pages and knowledge_chunks tables

Revision ID: 009
Revises: 008_wrong_book_fields
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '009'
down_revision: Union[str, None] = '008_wrong_book_fields'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    # document_pages
    op.create_table(
        'document_pages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('page_no', sa.Integer(), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('image_path', sa.String(1024), nullable=True),
        sa.Column('char_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('text_coverage', sa.Float(), nullable=True),
        sa.Column('page_type', sa.String(16), nullable=True),
        sa.Column('layout', postgresql.JSONB(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'page_no'),
    )
    op.create_index('ix_document_pages_document_id', 'document_pages', ['document_id'])

    # knowledge_chunks
    op.create_table(
        'knowledge_chunks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('page_from', sa.Integer(), nullable=False),
        sa.Column('page_to', sa.Integer(), nullable=False),
        sa.Column('question_no', sa.String(32), nullable=True),
        sa.Column('section_path', sa.String(512), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('private_content', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('visibility', sa.String(16), nullable=False, server_default='public'),
        sa.Column('material_type', sa.String(32), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('image_refs', postgresql.JSONB(), nullable=True),
        sa.Column('requires_vision', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('embedding_version', sa.String(64), nullable=True),
        sa.Column('document_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_knowledge_chunks_document_id', 'knowledge_chunks', ['document_id'])
    # pgvector 向量列（raw SQL）
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS vector vector(1536)")
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS search_vector tsvector")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_vector "
        "ON knowledge_chunks USING hnsw (vector vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 200)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_search_vector "
        "ON knowledge_chunks USING gin (search_vector)"
    )


def downgrade() -> None:
    op.drop_table('knowledge_chunks')
    op.drop_table('document_pages')
