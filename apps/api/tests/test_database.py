"""数据库层测试 — 模型 metadata、迁移和 Session。

需要 DATABASE_URL 的测试自动跳过。
"""

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
# 模型 metadata 测试（无数据库依赖）
# ============================================================

def test_all_models_registered_in_metadata() -> None:
    """验证全部模型已注册到 Base.metadata 中。"""
    import apps.api.db.models  # noqa: E402, F401
    from apps.api.db.base import Base  # noqa: E402

    table_names = Base.metadata.tables.keys()
    expected = {
        "users",
        "auth_sessions",
        "agent_runs",
        "agent_events",
        "idempotency_records",
        "documents",
        "ingestion_jobs",
        "chat_sessions",
        "chat_messages",
    }
    missing = expected - set(table_names)
    assert not missing, f"以下表未注册到 metadata: {missing}"


def test_agent_events_unique_constraint() -> None:
    """验证 agent_events 表包含 (run_id, sequence_no) 唯一约束。"""
    import apps.api.db.models  # noqa: E402, F401
    from apps.api.db.base import Base  # noqa: E402

    table = Base.metadata.tables["agent_events"]
    constraint_names = {c.name for c in table.constraints}
    assert "uq_agent_events_run_seq" in constraint_names


def test_idempotency_unique_constraint() -> None:
    """验证 idempotency_records 表包含三元组唯一约束。"""
    import apps.api.db.models  # noqa: E402, F401
    from apps.api.db.base import Base  # noqa: E402

    table = Base.metadata.tables["idempotency_records"]
    constraint_names = {c.name for c in table.constraints}
    assert "uq_idempotency_user_scope_key" in constraint_names


def test_auth_sessions_no_raw_token_column() -> None:
    """验证 auth_sessions 表没有 raw_token 列（只存 token_hash）。"""
    import apps.api.db.models  # noqa: E402, F401
    from apps.api.db.base import Base  # noqa: E402

    table = Base.metadata.tables["auth_sessions"]
    column_names = {c.name for c in table.columns}
    assert "token_hash" in column_names
    assert "raw_token" not in column_names
    assert "token" not in column_names


# ============================================================
# Alembic 迁移测试（无需数据库）
# ============================================================

def test_migration_file_exists_and_valid() -> None:
    """验证迁移文件存在，且 upgrade/downgrade 函数可导入。"""
    from importlib import util as import_util

    versions_dir = _project_root / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*.py"))
    assert len(migration_files) > 0, "没有找到迁移文件"

    for mf in migration_files:
        spec = import_util.spec_from_file_location("migration", mf)
        assert spec is not None, f"无法加载迁移文件: {mf}"
        mod = import_util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        assert hasattr(mod, "upgrade"), f"迁移文件缺少 upgrade(): {mf}"
        assert hasattr(mod, "downgrade"), f"迁移文件缺少 downgrade(): {mf}"
        assert hasattr(mod, "revision"), f"迁移文件缺少 revision: {mf}"


# ============================================================
# Session 测试（需要数据库）
# ============================================================

@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_async_session_commit() -> None:
    """验证 AsyncSession 可以提交简单查询。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    url = _to_async_url(DATABASE_URL)
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        result = await session.execute(text("SELECT 1 AS ok"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == 1

    await engine.dispose()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_async_session_rollback() -> None:
    """验证 AsyncSession 回滚不抛异常。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    url = _to_async_url(DATABASE_URL)
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        await session.execute(
            text("CREATE TEMP TABLE _test_rollback (val int) ON COMMIT DELETE ROWS")
        )
        await session.execute(text("INSERT INTO _test_rollback (val) VALUES (42)"))
        await session.rollback()
        # 关键：验证 rollback 不抛异常

    await engine.dispose()


def _to_async_url(url: str) -> str:
    """将 DATABASE_URL 转为 asyncpg 驱动格式。"""
    for prefix in ("+psycopg_async", "+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)
