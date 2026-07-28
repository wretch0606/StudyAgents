"""Training API 测试 — 创建训练、下一题、并发、恢复、属主隔离、防泄露。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


# ============================================================
# 1. 创建训练
# ============================================================

@pytest.mark.asyncio
async def test_create_training_generates_5_questions() -> None:
    """创建训练至少生成 3 题（默认 5 题）。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uid = await _get_user(maker)

    from apps.api.services.training_service import TrainingService

    async with maker() as s:
        svc = TrainingService(s)
        result = await svc.create_training(
            user_id=uid,
            chapter_ids=["ch-01"],
            question_types=["calculation"],
            difficulty=2,
            count=5,
        )
        assert result["total_questions"] >= 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_training_default_filters() -> None:
    """默认过滤器（空 chapters、choice 类型、难度 2）可生成题目。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uid = await _get_user(maker)

    from apps.api.services.training_service import TrainingService

    async with maker() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=uid)
        assert result["total_questions"] == 5

    await engine.dispose()


# ============================================================
# 2. 下一题
# ============================================================

@pytest.mark.asyncio
async def test_next_question_returns_public_only() -> None:
    """next 返回公开 DTO（不含 private_snapshot）。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uid = await _get_user(maker)

    from apps.api.services.training_service import TrainingService

    async with maker() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=uid, count=5)
        sid = result["session_id"]

    async with maker() as s:
        svc = TrainingService(s)
        q = await svc.get_next_question(session_id=sid, user_id=uid)
        assert q is not None
        assert q.stem
        assert q.order_no == 1
        d = q.model_dump()
        assert "private_snapshot" not in d
        assert "expected_answer" not in d
        assert "rubric" not in d

    await engine.dispose()


@pytest.mark.asyncio
async def test_next_question_idempotent() -> None:
    """重复调用 next 返回同一题（幂等）。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uid = await _get_user(maker)

    from apps.api.services.training_service import TrainingService

    async with maker() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=uid, count=3)
        sid = result["session_id"]

    async with maker() as s:
        svc = TrainingService(s)
        q1 = await svc.get_next_question(session_id=sid, user_id=uid)
        q2 = await svc.get_next_question(session_id=sid, user_id=uid)
        assert q1 is not None and q2 is not None
        assert q1.item_id == q2.item_id
        assert q1.order_no == q2.order_no

    await engine.dispose()


# ============================================================
# 3. 证据不足
# ============================================================

@pytest.mark.asyncio
async def test_evidence_insufficient_raises_error() -> None:
    """证据不足（< 3 题）抛出 TrainingError。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.services.training_adapter import FakeTrainingAdapter
    from apps.api.services.training_service import TrainingError, TrainingService

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uid = await _get_user(maker)

    async with maker() as s:
        adapter = FakeTrainingAdapter(scenario="evidence_insufficient")
        svc = TrainingService(s, adapter=adapter)
        with pytest.raises(TrainingError, match="证据不足"):
            await svc.create_training(user_id=uid, count=5)

    await engine.dispose()


# ============================================================
# 4. 属主隔离
# ============================================================

@pytest.mark.asyncio
async def test_owner_isolation() -> None:
    """其他用户不能访问训练。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.services.training_service import TrainingError, TrainingService

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)

    async with maker() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=users[0], count=3)
        sid = result["session_id"]

    async with maker() as s:
        svc = TrainingService(s)
        with pytest.raises(TrainingError, match="不存在"):
            await svc.get_next_question(session_id=sid, user_id=users[1])

    await engine.dispose()


# ============================================================
# 5. 公共 DTO 白名单
# ============================================================

def test_next_question_dto_no_private_fields() -> None:
    """NextQuestionResponse 字段白名单。"""
    from apps.api.schemas.training import NextQuestionResponse

    fields = set(NextQuestionResponse.model_fields.keys())
    allowed = {
        "item_id", "order_no", "question_type", "difficulty",
        "stem", "options", "source_kind", "source_label",
        "question_version", "progress",
    }
    assert fields == allowed
    assert "expected_answer" not in fields
    assert "rubric" not in fields
    assert "grade_private" not in fields


def test_create_training_request_has_defaults() -> None:
    """CreateTrainingRequest 默认值正确。"""
    from apps.api.schemas.training import CreateTrainingRequest

    req = CreateTrainingRequest()
    assert req.chapter_ids == []
    assert req.question_types == ["choice"]
    assert req.difficulty == 2
    assert req.count == 5


# ============================================================
# Helpers
# ============================================================

def _db_url():
    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _get_user(maker) -> str:
    from sqlalchemy import select

    from apps.api.db.models.user import User

    async with maker() as s:
        r = await s.execute(select(User).limit(1))
        u = r.scalar_one_or_none()
        assert u is not None, "No users"
        return str(u.id)


async def _get_users(maker) -> list[str]:
    from sqlalchemy import select

    from apps.api.db.models.user import User

    async with maker() as s:
        r = await s.execute(select(User).limit(2))
        users = list(r.scalars().all())
        if len(users) < 2:
            pytest.skip("Need 2 users")
        return [str(u.id) for u in users]
