"""004: documents 记录持久文件位置和大小。

Revision ID: 004
Revises: 003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("storage_name", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "size_bytes")
    op.drop_column("documents", "storage_name")
