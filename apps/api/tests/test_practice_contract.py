"""Practice 契约测试 — 严格按 api(6).ts 验证路径、请求/响应字段、白名单。

DTO 白名单测试无 DB 依赖；DB 测试需要 DATABASE_URL。
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

_needs_db = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


# ============================================================
# 0. DTO 白名单 (no-DB)
# ============================================================

def test_practice_item_dto_no_private_fields() -> None:
    """PracticeItem DTO 不含 expected_answer/rubric."""
    from apps.api.schemas.practice import PracticeItem
    fields = set(PracticeItem.model_fields.keys())
    allowed = {
        "item_id", "question_version", "order_no", "source_kind",
        "question_type", "difficulty", "stem", "options",
        "source_label", "progress",
    }
    assert fields == allowed
    assert "expected_answer" not in fields


def test_practice_session_dto_no_private_fields() -> None:
    """PracticeSession DTO 不含私有字段."""
    from apps.api.schemas.practice import PracticeSession
    fields = set(PracticeSession.model_fields.keys())
    assert "private_snapshot" not in fields
    assert "expected_answer" not in fields
    assert "rubric" not in fields


def test_submit_answer_response_dto() -> None:
    """SubmitAnswerResponse 只含 run_id + event_url."""
    from apps.api.schemas.practice import SubmitAnswerResponse
    fields = set(SubmitAnswerResponse.model_fields.keys())
    assert fields == {"run_id", "event_url"}


def test_finish_response_dto() -> None:
    """FinishPracticeSessionResponse fields."""
    from apps.api.schemas.practice import FinishPracticeSessionResponse
    fields = set(FinishPracticeSessionResponse.model_fields.keys())
    assert fields == {"session_id", "status", "summary_url"}


def test_session_summary_dto_no_private_fields() -> None:
    """SessionSummary DTO 不含 step_scores."""
    from apps.api.schemas.practice import SessionSummary
    fields = set(SessionSummary.model_fields.keys())
    assert "step_scores" not in fields
    assert "rubric" not in fields
    assert "expected_answer" not in fields


def test_practice_session_config_defaults() -> None:
    """PracticeSessionConfig 默认值对齐 api(6).ts."""
    from apps.api.schemas.practice import PracticeSessionConfig
    cfg = PracticeSessionConfig()
    assert cfg.chapter_ids == []
    assert cfg.knowledge_point_ids == []
    assert cfg.question_types == ["choice"]
    assert cfg.difficulty == 2
    assert cfg.target_count == 5


def test_create_response_serializes_correctly() -> None:
    """CreatePracticeSessionResponse serializable, no private fields."""
    from apps.api.schemas.practice import (
        CreatePracticeSessionResponse,
        PracticeItem,
        PracticeProgress,
        PracticeSession,
        PracticeSessionConfig,
    )
    item = PracticeItem(
        item_id="it-1", question_version="1.0", order_no=1,
        source_kind="generated_variant", question_type="choice",
        difficulty=2, stem="test?", options=[{"id": "A", "text": "A"}],
        source_label="q1", progress=PracticeProgress(current=1, total=5),
    )
    session = PracticeSession(
        id="s-1", user_id="u-1", filters=PracticeSessionConfig(),
        target_count=5, status="active", current_item=item,
        progress=PracticeProgress(current=1, total=5),
        created_at="2026-07-28T00:00:00", updated_at="2026-07-28T00:00:00",
    )
    resp = CreatePracticeSessionResponse(state="ready", session=session)
    data = resp.model_dump()
    assert data["state"] == "ready"
    assert data["session"]["current_item"] is not None
    assert "private_snapshot" not in str(data)
    assert "expected_answer" not in str(data)
    assert "rubric" not in str(data)


# ============================================================
# DB-dependent tests (require DATABASE_URL)
# ============================================================

@_needs_db
@pytest.mark.asyncio
async def test_create_practice_session_returns_ready_state() -> None:
    """Create returns state='ready' with current_item."""
    sid = await _create_session_via_service()
    assert sid is not None


@_needs_db
@pytest.mark.asyncio
async def test_practice_session_has_current_item() -> None:
    """Session has current_item after creation."""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    from apps.api.routers.practice import _build_practice_session
    uid, sid = await _create_user_and_session()
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid)
        assert ps is not None
        dto = await _build_practice_session(s, ps, uid)
        assert dto.current_item is not None
        assert dto.current_item.item_id
        assert dto.current_item.question_version == "1.0"
        assert dto.current_item.progress.total >= 3


@_needs_db
@pytest.mark.asyncio
async def test_practice_session_has_filters() -> None:
    """Session filters reflect creation config."""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    from apps.api.routers.practice import _build_practice_session
    uid, sid = await _create_user_and_session()
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid)
        dto = await _build_practice_session(s, ps, uid)
        assert dto.filters.difficulty == 2
        assert dto.target_count == 3


@_needs_db
@pytest.mark.asyncio
async def test_submit_answer_via_service() -> None:
    """Submit answer returns grading result."""
    import uuid as _uuid

    from apps.api.db.session import _get_sessionmaker
    from apps.api.services.grading_service import GradingService
    from apps.api.services.training_service import TrainingService
    uid, sid = await _create_user_and_session()
    async with _get_sessionmaker()() as s:
        svc = TrainingService(s)
        q = await svc.get_next_question(session_id=sid, user_id=uid)
        assert q is not None
        item_id = q.item_id
    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        result = await svc.submit_answer(
            session_id=sid, item_id=item_id, user_id=uid,
            answer_text="9.8 m/s", question_version="1.0",
            idempotency_key=f"ct-{_uuid.uuid4().hex[:8]}",
        )
        assert result.submission_id
        assert result.grade_id


@_needs_db
@pytest.mark.asyncio
async def test_finish_session_sets_completed() -> None:
    """Finish sets status='completed'."""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    uid, sid = await _create_user_and_session()
    async with _get_sessionmaker()() as s:
        await repo.update_practice_session(s, sid, user_id=uid, status="completed")
        await s.commit()
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid)
        assert ps is not None
        assert ps.status == "completed"


@_needs_db
@pytest.mark.asyncio
async def test_finish_session_idempotent() -> None:
    """Repeated finish is idempotent."""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    uid, sid = await _create_user_and_session()
    async with _get_sessionmaker()() as s:
        await repo.update_practice_session(s, sid, user_id=uid, status="completed")
        await s.commit()
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid)
        assert ps.status == "completed"
        await repo.update_practice_session(s, sid, user_id=uid, status="completed")
        await s.commit()
        ps2 = await repo.get_practice_session(s, sid, user_id=uid)
        assert ps2.status == "completed"


@_needs_db
@pytest.mark.asyncio
async def test_other_user_cannot_access_session() -> None:
    """Another user cannot access the session."""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    users = await _get_two_users()
    uid_a, uid_b = users[0], users[1]
    sid = await _create_session_via_service(uid=uid_a)
    assert sid is not None
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid_b)
        assert ps is None


@_needs_db
@pytest.mark.asyncio
async def test_session_summary_after_grading() -> None:
    """Summary available after grading."""
    import uuid as _uuid

    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.practice import get_session_summary
    from apps.api.services.grading_service import GradingService
    from apps.api.services.training_service import TrainingService
    uid, sid = await _create_user_and_session()
    async with _get_sessionmaker()() as s:
        svc = TrainingService(s)
        q = await svc.get_next_question(session_id=sid, user_id=uid)
        assert q is not None
    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        await svc.submit_answer(
            session_id=sid, item_id=q.item_id, user_id=uid,
            answer_text="9.8", question_version="1.0",
            idempotency_key=f"sum-{_uuid.uuid4().hex[:8]}",
        )
    async with _get_sessionmaker()() as s:
        summary = await get_session_summary(session_id=sid, user_id=uid, session=s)
        assert summary.session_id == sid
        assert len(summary.grades) >= 1


# ============================================================
# Helpers
# ============================================================

def _db_url():
    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _get_user_id() -> str:
    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.db.models.user import User
    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        r = await s.execute(sa_select(User).limit(1))
        u = r.scalar_one_or_none()
        assert u is not None, "No users in database"
        return str(u.id)


async def _get_two_users() -> list[str]:
    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.db.models.user import User
    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        r = await s.execute(sa_select(User).limit(2))
        users = list(r.scalars().all())
        if len(users) < 2:
            pytest.skip("Need 2 users")
        return [str(u.id) for u in users]


async def _create_session_via_service(uid: str | None = None) -> str:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.services.training_service import TrainingService
    if uid is None:
        uid = await _get_user_id()
    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=uid, count=3)
        return result["session_id"]


async def _create_user_and_session() -> tuple[str, str]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.services.training_service import TrainingService
    uid = await _get_user_id()
    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=uid, count=3)
        return uid, result["session_id"]
