"""Add Issue 16-5 fields to wrong_book_entries.

Revision ID: 008
Revises: 007
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("wrong_book_entries", sa.Column(
        "status", sa.String(32), nullable=False, server_default="pending",
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "source_kind", sa.String(32), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "source_label", sa.String(256), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "knowledge_point_id", sa.String(256), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "first_error_at", sa.DateTime(), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "last_error_at", sa.DateTime(), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "error_count", sa.Integer(), nullable=False, server_default="1",
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "last_score", sa.Float(), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "last_max_score", sa.Float(), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "next_review_at", sa.DateTime(), nullable=True,
    ))
    op.add_column("wrong_book_entries", sa.Column(
        "note", sa.Text(), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("wrong_book_entries", "note")
    op.drop_column("wrong_book_entries", "next_review_at")
    op.drop_column("wrong_book_entries", "last_max_score")
    op.drop_column("wrong_book_entries", "last_score")
    op.drop_column("wrong_book_entries", "error_count")
    op.drop_column("wrong_book_entries", "last_error_at")
    op.drop_column("wrong_book_entries", "first_error_at")
    op.drop_column("wrong_book_entries", "knowledge_point_id")
    op.drop_column("wrong_book_entries", "source_label")
    op.drop_column("wrong_book_entries", "source_kind")
    op.drop_column("wrong_book_entries", "status")
