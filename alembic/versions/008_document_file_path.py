"""Add file_path column to documents table.

Revision ID: 008
Revises: 007
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column(
        "file_path", sa.Text(), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("documents", "file_path")
