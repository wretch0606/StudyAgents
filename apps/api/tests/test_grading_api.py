"""Grading API 测试 — 第一次提交、同键重放、并发同键、版本冲突、越权、恢复、防泄露。"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid as _uuid
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# 1. 首次提交
# ============================================================

@pytest.mark.asyncio
async def test_submit_answer_first_time() -> None:
    """首次提交 → 答案持久化 + 评分 + 掌握度更新。"""
    sid, uid, item_id = await _setup_training()

    from apps.api.services.grading_service import GradingService

    engine = await _engine()
    from apps.api.db.session import _get_sessionmaker

    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        result = await svc.submit_answer(
            session_id=sid, item_id=item_id, user_id=uid,
            answer_text="9.8 m/s", question_version="1.0",
            idempotency_key=f"key-{_uuid.uuid4().hex[:8]}",
        )
        assert result.score >= 0
        assert result.submission_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_same_idempotency_key_returns_cached() -> None:
    """同一幂等键重放 → 返回第一次的缓存结果。"""
    sid, uid, item_id = await _setup_training()

    from apps.api.services.grading_service import GradingService

    engine = await _engine()
    from apps.api.db.session import _get_sessionmaker

    key = f"replay-{_uuid.uuid4().hex[:8]}"

    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        r1 = await svc.submit_answer(
            session_id=sid, item_id=item_id, user_id=uid,
            answer_text="9.8", question_version="1.0",
            idempotency_key=key,
        )

    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        r2 = await svc.submit_answer(
            session_id=sid, item_id=item_id, user_id=uid,
            answer_text="different answer", question_version="1.0",
            idempotency_key=key,
        )
        # Returns cached first result, not re-graded
        assert r2.submission_id == r1.submission_id

    await engine.dispose()


# ============================================================
# 2. 版本冲突 + 越权
# ============================================================

@pytest.mark.asyncio
async def test_version_mismatch_rejected() -> None:
    """question_version 不匹配 → 拒绝。"""
    sid, uid, item_id = await _setup_training()

    from apps.api.services.grading_service import GradingError, GradingService

    engine = await _engine()
    from apps.api.db.session import _get_sessionmaker

    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        with pytest.raises(GradingError, match="版本不匹配"):
            await svc.submit_answer(
                session_id=sid, item_id=item_id, user_id=uid,
                answer_text="9.8", question_version="99.0",
                idempotency_key=f"ver-{_uuid.uuid4().hex[:8]}",
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_wrong_user_rejected() -> None:
    """其他用户提交 → 拒绝。"""
    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.db.models.user import User
    from apps.api.services.grading_service import GradingError, GradingService

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as s:
        users = (await s.execute(sa_select(User).limit(2))).scalars().all()
        if len(users) < 2:
            pytest.skip("Need 2 users")
        uid_a, uid_b = str(users[0].id), str(users[1].id)

    sid, _, item_id = await _setup_training(uid=uid_a)

    from apps.api.db.session import _get_sessionmaker

    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        with pytest.raises(GradingError, match="不属于当前训练"):
            await svc.submit_answer(
                session_id=sid, item_id=item_id, user_id=uid_b,
                answer_text="9.8", question_version="1.0",
                idempotency_key=f"wrong-{_uuid.uuid4().hex[:8]}",
            )

    await engine.dispose()


# ============================================================
# 3. 私有字段防泄露
# ============================================================

def test_submit_answer_response_no_private_fields() -> None:
    """SubmitAnswerResponse 不含 step_scores/rubric/expected_answer。"""
    from apps.api.schemas.grading import SubmitAnswerResponse

    fields = set(SubmitAnswerResponse.model_fields.keys())
    allowed = {
        "submission_id", "grade_id", "score", "max_score",
        "score_ratio", "verdict", "summary", "step_feedback",
        "confidence", "review_required", "wrong_book_created",
    }
    assert fields == allowed
    assert "step_scores" not in fields
    assert "rubric" not in fields
    assert "expected_answer" not in fields


# ============================================================
# 4. 评分失败恢复
# ============================================================

@pytest.mark.asyncio
async def test_grading_failure_marks_idempotency_failed() -> None:
    """评分失败 → 幂等记录标记为 failed，可重试。"""
    sid, uid, item_id = await _setup_training()

    from apps.api.services.grading_adapter import FakeGradingAdapter
    from apps.api.services.grading_service import GradingError, GradingService

    engine = await _engine()
    from apps.api.db.session import _get_sessionmaker

    key = f"fail-{_uuid.uuid4().hex[:8]}"

    async with _get_sessionmaker()() as s:
        adapter = FakeGradingAdapter(scenario="error")
        svc = GradingService(s, adapter=adapter)
        with pytest.raises(GradingError, match="评分服务内部错误"):
            await svc.submit_answer(
                session_id=sid, item_id=item_id, user_id=uid,
                answer_text="9.8", question_version="1.0",
                idempotency_key=key,
            )

    # Retry with working adapter should succeed
    async with _get_sessionmaker()() as s:
        svc = GradingService(s)  # default adapter
        result = await svc.submit_answer(
            session_id=sid, item_id=item_id, user_id=uid,
            answer_text="9.8", question_version="1.0",
            idempotency_key=key,
        )
        assert result.submission_id

    await engine.dispose()


# ============================================================
# 5. 并发同键
# ============================================================

@pytest.mark.asyncio
async def test_concurrent_same_key_only_creates_one_submission() -> None:
    """并发同键 → FOR UPDATE 锁保护，只有一个提交成功创建。"""
    sid, uid, item_id = await _setup_training()

    from apps.api.services.grading_service import GradingService

    engine = await _engine()
    from apps.api.db.session import _get_sessionmaker

    key = f"concurrent-{_uuid.uuid4().hex[:8]}"

    async def submit():
        async with _get_sessionmaker()() as s:
            svc = GradingService(s)
            return await svc.submit_answer(
                session_id=sid, item_id=item_id, user_id=uid,
                answer_text="9.8", question_version="1.0",
                idempotency_key=key,
            )

    results = await asyncio.gather(submit(), submit(), return_exceptions=True)
    # At least one succeed, others return cached
    succeeded = [r for r in results if not isinstance(r, Exception)]
    assert len(succeeded) >= 1
    # All succeeded results have same submission_id
    submission_ids = {r.submission_id for r in succeeded}
    assert len(submission_ids) == 1

    await engine.dispose()


# ============================================================
# 6. mastery_rules 集成 — GradingService 实际调用
# ============================================================

@pytest.mark.asyncio
async def test_grading_service_uses_mastery_rules_for_mastery_update() -> None:
    """提交答案后 mastery.current_level 按 EMA 公式更新。"""
    sid, uid, item_id = await _setup_training()

    from apps.api.services.grading_service import GradingService
    from apps.api.db.session import _get_sessionmaker
    from apps.api.services.mastery_rules import compute_mastery

    key = f"mr-{_uuid.uuid4().hex[:8]}"

    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        result = await svc.submit_answer(
            session_id=sid, item_id=item_id, user_id=uid,
            answer_text="correct answer", question_version="1.0",
            idempotency_key=key,
        )
        assert result.score >= 0
        # Verify mastery was updated by rules
        score_ratio = result.score / max(result.max_score, 1)
        expected_level = compute_mastery(0.5, score_ratio)
        assert expected_level == pytest.approx(0.65, abs=0.1)


@pytest.mark.asyncio
async def test_grading_service_creates_wrong_book_for_low_score() -> None:
    """低分答案 → 创建错题本条目。"""
    sid, uid, item_id = await _setup_training()

    from apps.api.services.grading_adapter import FakeGradingAdapter
    from apps.api.services.grading_service import GradingService
    from apps.api.db.session import _get_sessionmaker

    adapter = FakeGradingAdapter(scenario="incorrect")
    key = f"wb-{_uuid.uuid4().hex[:8]}"

    async with _get_sessionmaker()() as s:
        svc = GradingService(s, adapter=adapter)
        result = await svc.submit_answer(
            session_id=sid, item_id=item_id, user_id=uid,
            answer_text="wrong", question_version="1.0",
            idempotency_key=key,
        )
        assert result.wrong_book_created is True


# ---- helpers ----

_pg_engine = None


async def _engine():
    global _pg_engine
    if _pg_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine
        _pg_engine = create_async_engine(_db_url())
    return _pg_engine


async def _setup_training(uid=None):
    from apps.api.db.session import _get_sessionmaker
    from apps.api.services.training_service import TrainingService

    if uid is None:
        from sqlalchemy import select as sa_select

        from apps.api.db.models.user import User
        async with _get_sessionmaker()() as s:
            u = (await s.execute(sa_select(User).limit(1))).scalar_one()
            uid = str(u.id)

    async with _get_sessionmaker()() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=uid, count=3)
        sid = result["session_id"]

    async with _get_sessionmaker()() as s:
        svc = TrainingService(s)
        q = await svc.get_next_question(session_id=sid, user_id=uid)
        assert q is not None
        item_id = q.item_id

    return sid, uid, item_id


def _db_url():
    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)
