"""003: ingestion_jobs 新增 error_code/error_summary/started_at/finished_at — Issue #11。

Revision ID: 003
Revises: 002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("error_code", sa.String(64), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("error_summary", sa.Text(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("finished_at", sa.DateTime(), nullable=True))
    # 将旧 error 列数据迁移到 error_summary（如果存在）
    op.execute(
        sa.text(
            "UPDATE ingestion_jobs SET error_summary = error "
            "WHERE error IS NOT NULL AND error_summary IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "finished_at")
    op.drop_column("ingestion_jobs", "started_at")
    op.drop_column("ingestion_jobs", "error_summary")
    op.drop_column("ingestion_jobs", "error_code")
