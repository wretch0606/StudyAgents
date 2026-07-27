"""004: Chat persistence — chat_sessions, chat_messages, AgentRun extensions.

Revision ID: 004
Revises: 003
Create Date: 2026-07-27

Creates:
  - chat_sessions    (conversation container)
  - chat_messages    (user/assistant messages with idempotency)

Alters:
  - agent_runs       (trace_id, run_type, last_successful_node, checkpoint_ref,
                      timing, error_code, retryable, updated_at)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 1. chat_sessions ----
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_foreign_key(
        "fk_chat_sessions_user_id",
        "chat_sessions", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )

    # ---- 2. chat_messages ----
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_messages_session_id", "chat_messages", ["session_id"],
    )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])
    op.create_index("ix_chat_messages_run_id", "chat_messages", ["run_id"])
    op.create_index(
        "uq_chat_messages_assistant_run",
        "chat_messages",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("role = 'assistant' AND run_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_chat_messages_session_id",
        "chat_messages", "chat_sessions",
        ["session_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_chat_messages_user_id",
        "chat_messages", "users",
        ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_chat_messages_run_id",
        "chat_messages", "agent_runs",
        ["run_id"], ["id"],
        ondelete="SET NULL",
    )

    # ---- 3. ALTER agent_runs — new columns + indexes ----
    op.add_column("agent_runs",
                  sa.Column("trace_id", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_agent_runs_trace_id", "agent_runs", ["trace_id"],
    )

    op.add_column("agent_runs",
                  sa.Column("run_type", sa.String(32), nullable=False,
                            server_default="qa"))
    op.add_column("agent_runs",
                  sa.Column("last_successful_node", sa.String(64), nullable=True))
    op.add_column("agent_runs",
                  sa.Column("checkpoint_ref", sa.String(256), nullable=True))
    op.add_column("agent_runs",
                  sa.Column("timing", postgresql.JSONB(), nullable=True))
    op.add_column("agent_runs",
                  sa.Column("error_code", sa.String(64), nullable=True))
    op.add_column("agent_runs",
                  sa.Column("retryable", sa.Boolean(), nullable=True))
    op.add_column("agent_runs",
                  sa.Column("updated_at", sa.DateTime(),
                            server_default=sa.func.now(), nullable=False))

    op.create_index("ix_agent_runs_run_type", "agent_runs", ["run_type"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])


def downgrade() -> None:
    # ---- Reverse agent_runs alterations ----
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_run_type", table_name="agent_runs")

    op.drop_column("agent_runs", "updated_at")
    op.drop_column("agent_runs", "retryable")
    op.drop_column("agent_runs", "error_code")
    op.drop_column("agent_runs", "timing")
    op.drop_column("agent_runs", "checkpoint_ref")
    op.drop_column("agent_runs", "last_successful_node")
    op.drop_column("agent_runs", "run_type")
    op.drop_constraint(
        "uq_agent_runs_trace_id", "agent_runs", type_="unique",
    )
    op.drop_column("agent_runs", "trace_id")

    # ---- Drop chat_messages ----
    op.drop_table("chat_messages")

    # ---- Drop chat_sessions ----
    op.drop_table("chat_sessions")
