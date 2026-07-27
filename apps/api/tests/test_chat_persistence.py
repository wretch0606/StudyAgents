"""Chat persistence tests — models, metadata, constraints, state machine, migration.

Requires DATABASE_URL for integration-level tests; auto-skipped otherwise.
"""

from __future__ import annotations

import os
import sys
import uuid as _uuid
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")


# ============================================================
# 1. Model metadata tests (no DB needed)
# ============================================================

def test_chat_tables_in_metadata() -> None:
    """Verify chat_sessions and chat_messages are registered in Base.metadata."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table_names = set(Base.metadata.tables.keys())
    for expected in ("chat_sessions", "chat_messages"):
        assert expected in table_names, f"Table '{expected}' missing from metadata"


def test_agent_runs_has_new_columns() -> None:
    """Verify AgentRun table has all new columns from 004 migration."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["agent_runs"]
    col_names = {c.name for c in table.columns}
    expected_new = {
        "trace_id", "run_type", "last_successful_node",
        "checkpoint_ref", "timing", "error_code", "retryable", "updated_at",
    }
    missing = expected_new - col_names
    assert not missing, f"AgentRun missing columns: {missing}"


def test_chat_messages_partial_unique_index() -> None:
    """Verify the partial unique index exists on chat_messages.run_id."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["chat_messages"]
    index_names = {idx.name for idx in table.indexes}
    assert "uq_chat_messages_assistant_run" in index_names


def test_agent_runs_trace_id_unique() -> None:
    """Verify trace_id has a unique constraint."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["agent_runs"]
    constraint_names = {c.name for c in table.constraints}
    assert "uq_agent_runs_trace_id" in constraint_names


def test_chat_sessions_has_user_id_index() -> None:
    """Verify chat_sessions has index on user_id."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["chat_sessions"]
    indexed = set()
    for idx in table.indexes:
        for col in idx.columns:
            indexed.add(col.name)
    assert "user_id" in indexed, "chat_sessions missing index on user_id"


def test_chat_messages_has_core_indexes() -> None:
    """Verify chat_messages has indexes on session_id, user_id, run_id."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["chat_messages"]
    indexed = set()
    for idx in table.indexes:
        for col in idx.columns:
            indexed.add(col.name)
    for expected in ("session_id", "user_id", "run_id"):
        assert expected in indexed, f"chat_messages missing index on {expected}"


def test_agent_runs_has_new_indexes() -> None:
    """Verify agent_runs has indexes on run_type and status."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["agent_runs"]
    indexed = set()
    for idx in table.indexes:
        for col in idx.columns:
            indexed.add(col.name)
    for expected in ("run_type", "status"):
        assert expected in indexed, f"agent_runs missing index on {expected}"


def test_agent_events_unique_constraint() -> None:
    """Verify agent_events has (run_id, sequence_no) unique constraint (Issue #8)."""
    import apps.api.db.models  # noqa: F401
    from apps.api.db.base import Base

    table = Base.metadata.tables["agent_events"]
    constraint_names = {c.name for c in table.constraints}
    assert "uq_agent_events_run_seq" in constraint_names


# ============================================================
# 2. Migration tests (no DB needed)
# ============================================================

def test_migration_004_importable() -> None:
    """Verify migration 004 file exists and has upgrade/downgrade/revision."""
    from importlib import util as import_util

    mf = _project_root / "alembic" / "versions" / "004_chat_persistence.py"
    assert mf.exists(), f"Migration file not found: {mf}"

    spec = import_util.spec_from_file_location("migration_004", mf)
    assert spec is not None
    mod = import_util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    assert hasattr(mod, "upgrade"), "Migration 004 missing upgrade()"
    assert hasattr(mod, "downgrade"), "Migration 004 missing downgrade()"
    assert hasattr(mod, "revision"), "Migration 004 missing revision"
    assert mod.revision == "004"
    assert mod.down_revision == "003"


# ============================================================
# 3. State machine tests (no DB needed)
# ============================================================

def test_valid_transitions_do_not_raise() -> None:
    """Verify all defined valid transitions succeed."""
    from apps.api.db.models.run_state import validate_transition

    validate_transition("queued", "running")
    validate_transition("running", "completed")
    validate_transition("running", "failed")
    validate_transition("running", "cancelled")
    validate_transition("failed", "queued")


def test_invalid_transitions_raise_valueerror() -> None:
    """Verify invalid transitions raise ValueError."""
    from apps.api.db.models.run_state import validate_transition

    invalid_pairs = [
        ("queued", "completed"),
        ("queued", "failed"),
        ("completed", "running"),
        ("completed", "failed"),
        ("cancelled", "running"),
        ("running", "queued"),
        ("failed", "completed"),
    ]
    for current, target in invalid_pairs:
        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(current, target)


def test_unknown_status_raises_valueerror() -> None:
    """Verify unknown current or target status raises ValueError."""
    from apps.api.db.models.run_state import validate_transition

    with pytest.raises(ValueError, match="Unknown current status"):
        validate_transition("bogus", "running")
    with pytest.raises(ValueError, match="Unknown target status"):
        validate_transition("queued", "bogus")


# ============================================================
# 4. Repository owner-isolation tests (needs DB)
# ============================================================

def _to_async_url(url: str) -> str:
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_chat_session_owner_isolation() -> None:
    """Verify get_chat_session filters by user_id when provided."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from apps.api.db.models.user import User
    from apps.api.repositories.chat import create_chat_session, get_chat_session

    url = _to_async_url(DATABASE_URL)
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        result = await session.execute(sa_select(User).limit(2))
        users = list(result.scalars().all())
        if len(users) < 2:
            pytest.skip("Need at least 2 users for owner isolation test")

        user_a, user_b = users[0], users[1]
        sid = str(_uuid.uuid4())
        tid = str(_uuid.uuid4())

        await create_chat_session(
            session, session_id=sid, user_id=user_a.id, thread_id=tid,
        )

        # User A can retrieve their own session
        found = await get_chat_session(session, sid, user_id=user_a.id)
        assert found is not None
        assert found.id == sid

        # User B should NOT be able to retrieve user A's session
        not_found = await get_chat_session(session, sid, user_id=user_b.id)
        assert not_found is None

    await engine.dispose()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_duplicate_assistant_message_raises() -> None:
    """Verify inserting two assistant messages for the same run fails."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from apps.api.db.models.agent_run import AgentRun
    from apps.api.db.models.chat_session import ChatSession
    from apps.api.db.models.user import User
    from apps.api.repositories.chat import insert_message

    url = _to_async_url(DATABASE_URL)
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        async with session.begin():
            user_result = await session.execute(sa_select(User).limit(1))
            user = user_result.scalar_one_or_none()
            if user is None:
                pytest.skip("No users for integration test")

            sid = str(_uuid.uuid4())
            tid = str(_uuid.uuid4())
            rid = str(_uuid.uuid4())

            chat = ChatSession(id=sid, user_id=user.id, thread_id=tid)
            session.add(chat)

            run = AgentRun(id=rid, thread_id=tid, user_id=user.id, mode="qa")
            session.add(run)
            await session.flush()

            # First assistant message — succeeds
            await insert_message(
                session, session_id=sid, user_id=user.id,
                role="assistant", content="Answer 1", run_id=rid,
            )

            # Second assistant message with same run_id — MUST fail
            with pytest.raises(Exception):
                await insert_message(
                    session, session_id=sid, user_id=user.id,
                    role="assistant", content="Answer 2", run_id=rid,
                )
                await session.flush()

    await engine.dispose()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_trace_id_unique_constraint() -> None:
    """Verify two agent runs cannot share the same trace_id."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from apps.api.db.models.agent_run import AgentRun
    from apps.api.db.models.user import User

    url = _to_async_url(DATABASE_URL)
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        async with session.begin():
            user_result = await session.execute(sa_select(User).limit(1))
            user = user_result.scalar_one_or_none()
            if user is None:
                pytest.skip("No users for integration test")

            trace = f"trace-{_uuid.uuid4().hex[:16]}"

            run1 = AgentRun(
                id=str(_uuid.uuid4()),
                thread_id=str(_uuid.uuid4()),
                user_id=user.id,
                mode="qa",
                trace_id=trace,
            )
            session.add(run1)
            await session.flush()

            run2 = AgentRun(
                id=str(_uuid.uuid4()),
                thread_id=str(_uuid.uuid4()),
                user_id=user.id,
                mode="qa",
                trace_id=trace,
            )
            session.add(run2)
            with pytest.raises(Exception):
                await session.flush()

    await engine.dispose()
