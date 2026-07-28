"""Add filters and target_count columns to practice_sessions.

Revision ID: 006
Revises: 005
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "practice_sessions",
        sa.Column("filters", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "practice_sessions",
        sa.Column("target_count", sa.Integer(), nullable=False, server_default="5"),
    )


def downgrade() -> None:
    op.drop_column("practice_sessions", "target_count")
    op.drop_column("practice_sessions", "filters")
