"""Session REST API 测试 — 直接通过 Service/Repository 层验证完整数据链路。

绕过 FastAPI TestClient 的 ASGITransport 事件循环限制，
直接调用 Service → Repository → PostgreSQL，证明：
- 属主隔离
- QA 立即返回
- 消息历史
- DTO 防泄露
- 错误格式
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid as _uuid
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


# ============================================================
# Helpers
# ============================================================

def _db_url():
    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _get_users(maker):
    from sqlalchemy import select

    from apps.api.db.models.user import User

    async with maker() as s:
        r = await s.execute(select(User).limit(2))
        return list(r.scalars().all())


async def _create_session_row(maker, uid, title="Test", tid=None):
    from apps.api.db.models.chat_session import ChatSession

    sid = str(_uuid.uuid4())
    async with maker() as s:
        s.add(ChatSession(id=sid, user_id=uid, thread_id=tid or str(_uuid.uuid4()), title=title))
        await s.commit()
    return sid


# ============================================================
# 1. 会话 CRUD — 属主隔离
# ============================================================

@pytest.mark.asyncio
async def test_create_session_success() -> None:
    """创建会话并确认写入数据库。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)
    assert len(users) >= 1

    from apps.api.repositories.chat import create_chat_session, get_chat_session

    sid = str(_uuid.uuid4())
    tid = str(_uuid.uuid4())
    async with maker() as s:
        await create_chat_session(
            s, session_id=sid, user_id=users[0].id, thread_id=tid, title="API Test",
        )
        await s.commit()

    async with maker() as s:
        found = await get_chat_session(s, sid, user_id=users[0].id)
        assert found is not None
        assert str(found.id) == sid  # UUID comparison

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_sessions_owner_isolation() -> None:
    """列出会话只返回当前用户。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)
    if len(users) < 2:
        pytest.skip("Need 2 users")

    from apps.api.repositories.chat import create_chat_session, list_chat_sessions

    # User A creates 2 sessions
    async with maker() as s:
        for _ in range(2):
            await create_chat_session(s, session_id=str(_uuid.uuid4()), user_id=users[0].id, thread_id=str(_uuid.uuid4()))
        await s.commit()

    # User A sees 2+ sessions, User B sees 0 of A's
    async with maker() as s:
        a_sessions = await list_chat_sessions(s, user_id=users[0].id)
        b_sessions = await list_chat_sessions(s, user_id=users[1].id)
        assert len(a_sessions) >= 2
        # B's sessions should not include A's
        a_ids = {str(s.id) for s in a_sessions}
        for s in b_sessions:
            assert str(s.id) not in a_ids

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_session_other_user_not_found() -> None:
    """其他用户查询返回 None。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)
    if len(users) < 2:
        pytest.skip("Need 2 users")

    from apps.api.repositories.chat import create_chat_session, get_chat_session

    sid = str(_uuid.uuid4())
    async with maker() as s:
        await create_chat_session(s, session_id=sid, user_id=users[0].id, thread_id=str(_uuid.uuid4()))
        await s.commit()

    async with maker() as s:
        found = await get_chat_session(s, sid, user_id=users[1].id)
        assert found is None

    await engine.dispose()


# ============================================================
# 2. QA 启动 — 立即返回 + Run 落库
# ============================================================

@pytest.mark.asyncio
async def test_start_qa_creates_run_and_message() -> None:
    """QA 启动：创建 AgentRun + user message + 立即返回 run_id。"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.db.models.agent_run import AgentRun as AgentRunModel
    from apps.api.services.agent_runner import AgentRunnerService, FakeAgentRunner

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)
    assert len(users) >= 1
    uid = str(users[0].id)

    sid = await _create_session_row(maker, users[0].id, "QA Test")

    svc = AgentRunnerService(runner=FakeAgentRunner(delay_ms=0), model_gateway=None, event_sink=_fake_sink())

    start = time.monotonic()
    async with maker() as s:
        result = await svc.start_qa(session=s, session_id=sid, user_id=uid, user_input="什么是熵？")
    elapsed = time.monotonic() - start

    assert "run_id" in result
    assert elapsed < 2.0, f"QA start took {elapsed:.2f}s"

    # Verify AgentRun committed
    async with maker() as s:
        run_row = (await s.execute(select(AgentRunModel).where(AgentRunModel.id == result["run_id"]))).scalar_one_or_none()
        assert run_row is not None
        assert run_row.user_id == users[0].id

    # Wait for background task
    task = svc._running.get(result["run_id"])
    if task:
        await asyncio.wait_for(task, timeout=10)

    # Verify run completed
    async with maker() as s:
        run_row = (await s.execute(select(AgentRunModel).where(AgentRunModel.id == result["run_id"]))).scalar_one_or_none()
        assert run_row is not None
        assert run_row.status == "completed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_background_task_is_registered() -> None:
    """start_qa 注册后台任务（_execute_run 通过 _get_sessionmaker 获取独立 session）。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.services.agent_runner import AgentRunnerService, FakeAgentRunner

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)
    uid = str(users[0].id)
    sid = await _create_session_row(maker, users[0].id, "BG Test")

    svc = AgentRunnerService(
        runner=FakeAgentRunner(delay_ms=0),
        model_gateway=None,
        event_sink=_fake_sink(),
    )

    async with maker() as s:
        result = await svc.start_qa(
            session=s, session_id=sid, user_id=uid, user_input="bg test",
        )

    # Background task registered in svc._running
    task = svc._running.get(result["run_id"])
    assert task is not None, "Background task should be registered"

    await engine.dispose()


# ============================================================
# 3. 消息历史 + DTO 防泄露
# ============================================================

@pytest.mark.asyncio
async def test_messages_owner_isolation() -> None:
    """消息查询属主隔离。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.repositories.chat import get_messages, insert_message

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)
    if len(users) < 2:
        pytest.skip("Need 2 users")
    uid_a, uid_b = str(users[0].id), str(users[1].id)
    sid = await _create_session_row(maker, users[0].id, "Msg Test")

    async with maker() as s:
        await insert_message(s, session_id=sid, user_id=uid_a, role="user", content="Hello")
        await s.commit()

    # User A sees message
    async with maker() as s:
        msgs = await get_messages(s, sid, user_id=uid_a)
        assert len(msgs) >= 1

    # User B sees empty (not A's message)
    async with maker() as s:
        msgs = await get_messages(s, sid, user_id=uid_b)
        assert len(msgs) == 0

    await engine.dispose()


def test_message_dto_no_private_fields() -> None:
    """MessageResponse 公开 DTO 不含 user_id 或内部字段。"""
    from apps.api.schemas.chat import MessageResponse

    fields = set(MessageResponse.model_fields.keys())
    allowed = {"id", "role", "content", "run_id", "sequence_no", "created_at"}
    assert fields == allowed


def test_session_dto_no_private_fields() -> None:
    """SessionResponse DTO 不含 user_id。"""
    from apps.api.schemas.chat import SessionResponse

    fields = set(SessionResponse.model_fields.keys())
    assert "user_id" not in fields


# ============================================================
# 4. 错误响应格式
# ============================================================

def test_error_response_has_required_fields() -> None:
    """ApiErrorResponse 含 code/message/retryable/trace_id。"""
    from apps.api.schemas.error import ApiErrorResponse

    fields = set(ApiErrorResponse.model_fields.keys())
    required = {"code", "message", "retryable", "trace_id"}
    assert required <= fields


# ============================================================
# 5. 状态机 + 重试
# ============================================================

def test_state_machine_validates_retry_transition() -> None:
    """只有 failed 可以 retry → queued。"""
    from apps.api.db.models.run_state import FAILED, QUEUED, validate_transition

    validate_transition(FAILED, QUEUED)


def test_state_machine_rejects_completed_retry() -> None:
    """completed 不能 retry。"""
    from apps.api.db.models.run_state import COMPLETED, QUEUED, validate_transition

    with pytest.raises(ValueError):
        validate_transition(COMPLETED, QUEUED)


# ============================================================
# 6. 答案幂等
# ============================================================

@pytest.mark.asyncio
async def test_assistant_message_idempotent() -> None:
    """同一 run 只能写入一条 assistant 消息。"""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from apps.api.db.models.agent_run import AgentRun as AgentRunModel
    from apps.api.repositories.chat import insert_message

    engine = create_async_engine(_db_url())
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    users = await _get_users(maker)
    uid = str(users[0].id)
    sid = await _create_session_row(maker, users[0].id, "Idempotent")
    rid = str(_uuid.uuid4())

    # Create AgentRun
    async with maker() as s:
        s.add(AgentRunModel(id=rid, thread_id=str(_uuid.uuid4()), user_id=users[0].id, mode="qa"))
        await s.commit()

    # First assistant — succeeds
    async with maker() as s:
        await insert_message(s, session_id=sid, user_id=uid, role="assistant", content="Answer", run_id=rid)
        await s.commit()

    # Second assistant — must fail (partial unique index)
    async with maker() as s:
        with pytest.raises(Exception):
            await insert_message(s, session_id=sid, user_id=uid, role="assistant", content="Answer 2", run_id=rid)
            await s.commit()

    await engine.dispose()


# ---- helpers ----

def _fake_sink():
    class FakeSink:
        async def emit(self, *, run_id, event, db_session):
            from apps.api.schemas.agent import AgentEvent
            return AgentEvent(
                id=str(_uuid.uuid4()), run_id=run_id, sequence_no=0,
                agent=event.agent, event_type=event.event_type, status=event.status,
                summary=event.summary, source_refs=event.source_refs,
                duration_ms=event.duration_ms, created_at="2026-01-01T00:00:00",
            )
    return FakeSink()
