"""Training data model tests — metadata, constraints, migration, private field layering."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")


# ============================================================
# 1. Metadata tests
# ============================================================

def test_all_new_tables_in_metadata() -> None:
    """全部 7 张新表注册到 Base.metadata。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table_names = set(Base.metadata.tables.keys())
    expected = {
        "practice_sessions", "practice_items",
        "answer_submissions", "grade_results",
        "wrong_book_entries", "mastery_records", "mastery_change_logs",
    }
    missing = expected - table_names
    assert not missing, f"Missing tables: {missing}"


def test_practice_items_unique_constraint() -> None:
    """(session_id, order_no) 唯一约束。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["practice_items"]
    names = {c.name for c in table.constraints}
    assert "uq_practice_items_session_order" in names


def test_answer_submissions_unique_constraint() -> None:
    """(item_id, attempt) 唯一约束 — 幂等提交。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["answer_submissions"]
    names = {c.name for c in table.constraints}
    assert "uq_answer_submissions_item_attempt" in names


def test_mastery_records_unique_constraint() -> None:
    """(user_id, knowledge_point) 唯一约束。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["mastery_records"]
    names = {c.name for c in table.constraints}
    assert "uq_mastery_user_kp" in names


def test_all_user_id_indexes() -> None:
    """所有新表都有 user_id 索引。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    tables_with_user = [
        "practice_sessions", "practice_items", "answer_submissions",
        "grade_results", "wrong_book_entries", "mastery_records",
    ]
    for tname in tables_with_user:
        table = Base.metadata.tables[tname]
        indexed = set()
        for idx in table.indexes:
            for col in idx.columns:
                indexed.add(col.name)
        assert "user_id" in indexed, f"{tname} missing user_id index"


def test_practice_item_has_private_snapshot_column() -> None:
    """practice_items 有 private_snapshot 列（私有层）。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["practice_items"]
    cols = {c.name for c in table.columns}
    assert "private_snapshot" in cols
    assert "public_snapshot" in cols


def test_grade_result_has_step_scores_private() -> None:
    """grade_results 有 step_scores 列（私有评分维度）。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["grade_results"]
    cols = {c.name for c in table.columns}
    assert "step_scores" in cols


def test_mastery_change_log_has_before_after() -> None:
    """mastery_change_logs 有 before/after 字段 + source_grade_id。"""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["mastery_change_logs"]
    cols = {c.name for c in table.columns}
    for expected in (
        "before_level", "after_level", "before_streak",
        "after_streak", "change_reason", "source_grade_id",
    ):
        assert expected in cols, f"Missing {expected}"


# ============================================================
# 2. Migration tests
# ============================================================

def test_migration_005_importable() -> None:
    """Migration 005 存在且可导入。"""
    from importlib import util as import_util

    mf = _project_root / "alembic" / "versions" / "005_training_data_model.py"
    assert mf.exists(), f"Migration file not found: {mf}"

    spec = import_util.spec_from_file_location("migration_005", mf)
    assert spec is not None
    mod = import_util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert mod.revision == "005"
    assert mod.down_revision == "004"


# ============================================================
# 3. Migration upgrade/downgrade cycle (requires DB)
# ============================================================

@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
def test_migration_005_upgrade_downgrade_cycle() -> None:
    """升级 → 降级 → 再升级 循环（使用 alembic CLI）。"""
    import subprocess
    import sys

    native_url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        native_url = native_url.replace(prefix, "")

    env = {**__import__("os").environ, "DATABASE_URL": native_url}

    def _run(cmd: list[str]) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c",
             str(_project_root / "alembic.ini")] + cmd,
            cwd=str(_project_root), capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, (
            f"alembic {' '.join(cmd)} failed:\n{result.stderr}"
        )

    # Upgrade to 005
    _run(["upgrade", "005"])
    # Downgrade to 004
    _run(["downgrade", "004"])
    # Re-upgrade to 005
    _run(["upgrade", "005"])
    # Cleanup: downgrade to 004 (tables removed)
    _run(["downgrade", "004"])
