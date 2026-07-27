"""005: Training data model — practice sessions, items, answers, grading, mastery.

Revision ID: 005
Revises: 004
Create Date: 2026-07-28

Creates:
  - practice_sessions
  - practice_items
  - answer_submissions
  - grade_results
  - wrong_book_entries
  - mastery_records
  - mastery_change_logs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- 1. practice_sessions ----
    op.create_table(
        "practice_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="practice"),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_sessions_user_id", "practice_sessions", ["user_id"])
    op.create_foreign_key(
        "fk_practice_sessions_user_id", "practice_sessions", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )

    # ---- 2. practice_items ----
    op.create_table(
        "practice_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False, server_default=""),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("source_label", sa.String(256), nullable=True),
        sa.Column("question_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("public_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("private_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "order_no", name="uq_practice_items_session_order"),
    )
    op.create_index("ix_practice_items_session_id", "practice_items", ["session_id"])
    op.create_index("ix_practice_items_user_id", "practice_items", ["user_id"])
    op.create_foreign_key(
        "fk_practice_items_session_id", "practice_items", "practice_sessions",
        ["session_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_practice_items_user_id", "practice_items", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_practice_items_run_id", "practice_items", "agent_runs",
        ["run_id"], ["id"], ondelete="SET NULL",
    )

    # ---- 3. answer_submissions ----
    op.create_table(
        "answer_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("answer_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("answer_json", postgresql.JSONB(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "attempt", name="uq_answer_submissions_item_attempt"),
    )
    op.create_index("ix_answer_submissions_item_id", "answer_submissions", ["item_id"])
    op.create_index("ix_answer_submissions_user_id", "answer_submissions", ["user_id"])
    op.create_foreign_key(
        "fk_answer_submissions_item_id", "answer_submissions", "practice_items",
        ["item_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_answer_submissions_user_id", "answer_submissions", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_answer_submissions_run_id", "answer_submissions", "agent_runs",
        ["run_id"], ["id"], ondelete="SET NULL",
    )

    # ---- 4. grade_results ----
    op.create_table(
        "grade_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("step_scores", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.String(64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("public_feedback", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grade_results_submission_id", "grade_results", ["submission_id"])
    op.create_index("ix_grade_results_user_id", "grade_results", ["user_id"])
    op.create_foreign_key(
        "fk_grade_results_submission_id", "grade_results", "answer_submissions",
        ["submission_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_grade_results_user_id", "grade_results", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_grade_results_run_id", "grade_results", "agent_runs",
        ["run_id"], ["id"], ondelete="SET NULL",
    )

    # ---- 5. wrong_book_entries ----
    op.create_table(
        "wrong_book_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("grade_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("stem_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("wrong_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("correct_answer", sa.Text(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wrong_book_entries_user_id", "wrong_book_entries", ["user_id"])
    op.create_foreign_key(
        "fk_wrong_book_entries_user_id", "wrong_book_entries", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_wrong_book_entries_item_id", "wrong_book_entries", "practice_items",
        ["item_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_wrong_book_entries_submission_id", "wrong_book_entries", "answer_submissions",
        ["submission_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_wrong_book_entries_grade_id", "wrong_book_entries", "grade_results",
        ["grade_id"], ["id"], ondelete="SET NULL",
    )

    # ---- 6. mastery_records ----
    op.create_table(
        "mastery_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_point", sa.String(256), nullable=False),
        sa.Column("topic", sa.String(128), nullable=True),
        sa.Column("current_level", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_practiced_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "knowledge_point", name="uq_mastery_user_kp"),
    )
    op.create_index("ix_mastery_records_user_id", "mastery_records", ["user_id"])

    # ---- 7. mastery_change_logs ----
    op.create_table(
        "mastery_change_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mastery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_reason", sa.String(128), nullable=False),
        sa.Column("source_grade_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_level", sa.Float(), nullable=False),
        sa.Column("after_level", sa.Float(), nullable=False),
        sa.Column("before_streak", sa.Integer(), nullable=True),
        sa.Column("after_streak", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_mastery_change_logs_mastery_id", "mastery_change_logs", "mastery_records",
        ["mastery_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_mastery_change_logs_user_id", "mastery_change_logs", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_mastery_change_logs_grade_id", "mastery_change_logs", "grade_results",
        ["source_grade_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_table("mastery_change_logs")
    op.drop_table("mastery_records")
    op.drop_table("wrong_book_entries")
    op.drop_table("grade_results")
    op.drop_table("answer_submissions")
    op.drop_table("practice_items")
    op.drop_table("practice_sessions")
