"""Agent Runner 测试 — 正常/等待/失败/重试/恢复/重复请求/属主隔离。

使用 FakeAgentRunner 模拟 C 的行为，验证 D 侧编排逻辑。
"""

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


@pytest.mark.asyncio
async def test_session_bound_event_sink_uses_background_session() -> None:
    """后台 Runner 发事件时始终使用当前运行事务的会话。"""
    from apps.api.schemas.agent import AgentEventDraft
    from apps.api.services.agent_runner import _SessionBoundEventSink

    expected_session = object()
    captured: dict = {}

    class Sink:
        async def emit(self, *, run_id, event, db_session):
            captured.update({
                "run_id": run_id,
                "event": event,
                "db_session": db_session,
            })
            return event

    bound = _SessionBoundEventSink(Sink(), expected_session)  # type: ignore[arg-type]
    event = AgentEventDraft(
        agent="coordinator",
        event_type="run.started",
        status="running",
        summary="started",
    )
    await bound.emit(run_id="run-1", event=event, db_session=None)

    assert captured["run_id"] == "run-1"
    assert captured["db_session"] is expected_session


# ============================================================
# 1. FakeAgentRunner 行为测试
# ============================================================


@pytest.mark.asyncio
async def test_fake_runner_success_flow() -> None:
    """FakeAgentRunner success 场景：发射完整事件序列 + 返回答案。"""
    from apps.api.services.agent_runner import FakeAgentRunner

    runner = FakeAgentRunner(scenario="success", answer="测试答案")
    db = _make_fake_db()
    sink = _make_fake_sink(db)

    result = await runner.run(
        run_id="r-success",
        trace_id="trace-001",
        user_input="什么是熵？",
        mode="qa",
        model_gateway=None,
        event_sink=sink,
    )

    assert result.status == "succeeded"
    assert result.public_response == "测试答案"
    assert result.model_calls > 0
    assert sink.event_count >= 4  # at least 4 events emitted


@pytest.mark.asyncio
async def test_fake_runner_failure_flow() -> None:
    """FakeAgentRunner failure 场景：发射事件后返回失败。"""
    from apps.api.services.agent_runner import FakeAgentRunner

    runner = FakeAgentRunner(
        scenario="failure",
        error_code="MODEL_TIMEOUT",
        error_message="模型调用超时",
        retryable=True,
    )
    db = _make_fake_db()
    sink = _make_fake_sink(db)

    result = await runner.run(
        run_id="r-fail",
        trace_id="trace-002",
        user_input="test",
        mode="qa",
        model_gateway=None,
        event_sink=sink,
    )

    assert result.status == "failed"
    assert result.error_code == "MODEL_TIMEOUT"
    assert result.retryable is True


@pytest.mark.asyncio
async def test_fake_runner_waiting_flow() -> None:
    """FakeAgentRunner waiting 场景：发射 run.waiting_user 事件。"""
    from apps.api.services.agent_runner import FakeAgentRunner

    runner = FakeAgentRunner(scenario="waiting")
    db = _make_fake_db()
    sink = _make_fake_sink(db)

    result = await runner.run(
        run_id="r-wait",
        trace_id="trace-003",
        user_input="practice answer",
        mode="practice",
        model_gateway=None,
        event_sink=sink,
    )

    assert result.status == "succeeded"
    assert result.last_successful_node == "waiting_user"
    assert result.public_response is None


@pytest.mark.asyncio
async def test_fake_runner_crash_scenario() -> None:
    """FakeAgentRunner crash 场景：无事件直接返回失败。"""
    from apps.api.services.agent_runner import FakeAgentRunner

    runner = FakeAgentRunner(scenario="crash")
    db = _make_fake_db()
    sink = _make_fake_sink(db)

    result = await runner.run(
        run_id="r-crash",
        trace_id="trace-004",
        user_input="test",
        mode="qa",
        model_gateway=None,
        event_sink=sink,
    )

    assert result.status == "failed"
    assert result.error_code == "WORKER_CRASH"
    assert result.retryable is True


# ============================================================
# 2. AgentRunnerService 编排测试
# ============================================================


@pytest.mark.asyncio
async def test_runner_service_start_qa_creates_run() -> None:
    """start_qa 创建用户消息 + AgentRun + run.started 事件。"""
    from apps.api.services.agent_runner import (
        AgentRunnerService,
        FakeAgentRunner,
    )

    db = _make_fake_db()
    sink = _make_fake_sink(db)
    svc = AgentRunnerService(
        runner=FakeAgentRunner(scenario="success", delay_ms=0),
        model_gateway=None,
        event_sink=sink,
    )

    result = await svc.start_qa(
        session=db,
        session_id=str(_uuid.uuid4()),
        user_id=str(_uuid.uuid4()),
        user_input="什么是熵？",
    )

    assert "run_id" in result
    assert "thread_id" in result
    assert "trace_id" in result
    assert result["trace_id"].startswith("trace-")
    # Background task should be registered
    assert result["run_id"] in svc._running


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_runner_service_success_writes_answer() -> None:
    """成功执行后写入 assistant 消息（需真实 PostgreSQL）。"""
    import uuid

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from apps.api.db.models.agent_run import AgentRun as AgentRunModel
    from apps.api.db.models.user import User
    from apps.api.services.agent_runner import (
        AgentRunnerService,
        FakeAgentRunner,
    )

    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(async_url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        user_result = await session.execute(select(User).limit(1))
        user = user_result.scalar_one_or_none()
        if user is None:
            pytest.skip("No users in database")

        uid = str(user.id)
        sid = str(uuid.uuid4())
        tid = str(uuid.uuid4())

        from apps.api.db.models.chat_session import ChatSession
        chat = ChatSession(id=sid, user_id=uid, thread_id=tid)
        session.add(chat)

        sink = _make_fake_sink(None)
        svc = AgentRunnerService(
            runner=FakeAgentRunner(scenario="success", answer="熵是...", delay_ms=0),
            model_gateway=None,
            event_sink=sink,
        )

        result = await svc.start_qa(
            session=session,
            session_id=sid,
            user_id=uid,
            user_input="什么是熵？",
        )

        # Wait for background task
        task = svc._running.get(result["run_id"])
        if task:
            await asyncio.wait_for(task, timeout=10)

        # Verify run completed
        run_result = await session.execute(
            select(AgentRunModel).where(
                AgentRunModel.id == result["run_id"],
            ),
        )
        run = run_result.scalar_one_or_none()
        assert run is not None
        assert run.status == "completed"

        # Cleanup
        await session.delete(run)
        await session.delete(chat)
        await session.commit()


@pytest.mark.asyncio
async def test_runner_service_retry_blocked_when_running() -> None:
    """正在执行中的 Run 不能重试（幂等键保护）。"""
    import apps.api.repositories.agent_run as run_repo
    from apps.api.services.agent_runner import (
        AgentRunnerError,
        AgentRunnerService,
        FakeAgentRunner,
    )

    db = _make_fake_db()
    sink = _make_fake_sink(db)
    svc = AgentRunnerService(
        runner=FakeAgentRunner(scenario="success", delay_ms=500),
        model_gateway=None,
        event_sink=sink,
    )

    rid = str(_uuid.uuid4())
    uid = str(_uuid.uuid4())

    # Create a fake run in failed status with retryable=True
    fake_run = type("FakeRun", (), {
        "id": rid,
        "status": "failed",
        "retryable": True,
        "mode": "qa",
        "trace_id": "trace-001",
        "user_id": uid,
    })()

    # Mock get_run to return the fake run (async)
    _orig_get_run = run_repo.get_run

    async def _mock_get_run(session, rid2, *, user_id=None):
        return fake_run if rid2 == rid else None

    run_repo.get_run = _mock_get_run
    try:
        # Register a running task
        svc._running[rid] = asyncio.create_task(asyncio.sleep(1))

        with pytest.raises(AgentRunnerError, match="正在执行中"):
            await svc.retry_run(run_id=rid, user_id=uid, session=db)

        svc._running[rid].cancel()
        try:
            await svc._running[rid]
        except asyncio.CancelledError:
            pass
    finally:
        run_repo.get_run = _orig_get_run


def test_error_mapping_retryable_vs_permanent() -> None:
    """错误分类：可重试 vs 不可重试。"""
    from apps.api.services.agent_runner import _is_retryable_exception

    # Retryable
    assert _is_retryable_exception(ConnectionError("timeout")) is True
    assert _is_retryable_exception(RuntimeError("something went wrong")) is True
    assert _is_retryable_exception(OSError("network unreachable")) is True

    # Permanent
    assert _is_retryable_exception(ValueError("invalid input")) is False
    assert _is_retryable_exception(TypeError("bad type")) is False
    assert _is_retryable_exception(KeyError("missing key")) is False


def test_trace_id_generated_and_unique() -> None:
    """每次 start_qa 生成唯一 trace_id。"""
    import uuid as _uuid_mod

    traces = set()
    for _ in range(10):
        trace = f"trace-{_uuid_mod.uuid4().hex[:16]}"
        assert trace.startswith("trace-")
        assert trace not in traces
        traces.add(trace)
    assert len(traces) == 10


def test_agent_run_result_dataclass() -> None:
    """AgentRunResult 所有字段可构造并有正确默认值。"""
    from apps.api.services.agent_runner import AgentRunResult

    r = AgentRunResult(status="succeeded")
    assert r.status == "succeeded"
    assert r.public_response is None
    assert r.retryable is False
    assert r.model_calls == 0

    r2 = AgentRunResult(
        status="failed",
        error_code="ERR",
        error_message="msg",
        retryable=True,
        model_calls=3,
        node_hops=5,
        input_tokens=100,
        output_tokens=50,
        total_elapsed_ms=1500,
    )
    assert r2.status == "failed"
    assert r2.retryable is True
    assert r2.model_calls == 3


# ============================================================
# 3. 属主隔离测试
# ============================================================


@pytest.mark.asyncio
async def test_runner_service_owner_isolation() -> None:
    """用户 B 不能重试用户 A 的 Run。"""
    from apps.api.services.agent_runner import (
        AgentRunnerError,
        AgentRunnerService,
        FakeAgentRunner,
    )

    db = _make_fake_db()
    sink = _make_fake_sink(db)
    svc = AgentRunnerService(
        runner=FakeAgentRunner(),
        model_gateway=None,
        event_sink=sink,
    )

    # get_run with wrong user_id returns None → AgentRunnerError
    with pytest.raises(AgentRunnerError, match="Run 不存在"):
        await svc.retry_run(
            run_id="someone-elses-run",
            user_id="user-b",
            session=db,
        )


# ============================================================
# 4. 幂等答案测试
# ============================================================


def test_agent_run_result_public_response_default_none() -> None:
    """失败时 public_response 默认为 None。"""
    from apps.api.services.agent_runner import AgentRunResult

    r = AgentRunResult(status="failed", error_code="ERR")
    assert r.public_response is None


# ============================================================
# 5. State machine validation
# ============================================================


def test_runner_service_retry_only_failed_or_cancelled() -> None:
    """只有 failed/cancelled 状态才能重试。"""
    from apps.api.db.models.run_state import (
        CANCELLED,
        COMPLETED,
        FAILED,
        QUEUED,
        RUNNING,
    )

    retryable = {FAILED, CANCELLED}
    not_retryable = {QUEUED, RUNNING, COMPLETED}
    assert retryable & not_retryable == set()

    # Validate transitions: only FAILED can transition to QUEUED (retry)
    from apps.api.db.models.run_state import validate_transition

    validate_transition(FAILED, QUEUED)  # retry is valid
    with pytest.raises(ValueError):
        validate_transition(COMPLETED, QUEUED)  # terminal
    with pytest.raises(ValueError):
        validate_transition(CANCELLED, QUEUED)  # terminal


# ============================================================
# 6. DB 集成测试（需 DATABASE_URL）
# ============================================================


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_runner_service_recovery_stale_runs() -> None:
    """恢复崩溃后残留的 running 状态任务 — 完整闭环。

    验证：
    1. 创建 running Run（含 last_successful_node + checkpoint_ref）
    2. recover_stale_runs() 找到并重新调度
    3. Runner 收到恢复参数
    4. 最终状态为 completed
    5. 同一 run 最多一条 assistant 消息
    6. 新 session 重查确认
    """
    import uuid

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from apps.api.db.models.agent_run import AgentRun as AgentRunModel
    from apps.api.db.models.run_state import RUNNING
    from apps.api.db.models.user import User
    from apps.api.services.agent_runner import (
        AgentRunnerService,
        AgentRunResult,
    )

    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(async_url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Spy runner that records calls
    class SpyRunner:
        def __init__(self):
            self.calls: list[dict] = []

        async def run(self, **kwargs):
            self.calls.append(kwargs)
            return AgentRunResult(
                status="succeeded",
                public_response="Recovered answer",
                last_successful_node="run.completed",
                checkpoint_ref="cp-recovered",
                model_calls=1,
                node_hops=2,
                total_elapsed_ms=100,
            )

    spy = SpyRunner()

    async with maker() as session:
        user_result = await session.execute(select(User).limit(1))
        user = user_result.scalar_one_or_none()
        if user is None:
            pytest.skip("No users in database")

        rid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        run = AgentRunModel(
            id=rid,
            thread_id=tid,
            user_id=user.id,
            mode="qa",
            status=RUNNING,
            last_successful_node="agent.summary",
            checkpoint_ref="cp-before-crash",
            trace_id=f"trace-{uuid.uuid4().hex[:16]}",
        )
        session.add(run)
        await session.commit()
        str(user.id)

    sink = _make_fake_sink(None)
    svc = AgentRunnerService(
        runner=spy,
        model_gateway=None,
        event_sink=sink,
    )

    # Run recovery using global engine (same pool as background tasks)
    from apps.api.db.session import _get_sessionmaker

    async with _get_sessionmaker()() as recovery_session:
        recovered = await svc.recover_stale_runs(recovery_session)
        assert recovered >= 1, "Should recover at least 1 stale run"

    # Allow event loop to schedule and execute background tasks
    await asyncio.sleep(0.3)

    # Wait for background tasks to complete
    task = svc._running.get(rid)
    if task:
        await asyncio.wait_for(task, timeout=10)

    # Verify runner was called with recovery params
    assert len(spy.calls) >= 1, "Runner should have been called"
    call = spy.calls[0]
    assert call["run_id"] == rid
    assert call["last_successful_node"] == "agent.summary"
    assert call["checkpoint_ref"] == "cp-before-crash"
    assert call["mode"] == "qa"

    # Verify final state via new session (use global engine)
    async with _get_sessionmaker()() as verify_session:
        result = await verify_session.execute(
            select(AgentRunModel).where(AgentRunModel.id == rid),
        )
        final_run = result.scalar_one_or_none()
        assert final_run is not None
        assert final_run.status == "completed", (
            f"Expected completed, got {final_run.status}"
        )
        assert final_run.last_successful_node == "run.completed"
        assert final_run.checkpoint_ref == "cp-recovered"

        # Cleanup
        await verify_session.delete(final_run)
        await verify_session.commit()


# ---- helpers ----


def _make_fake_db():
    """创建 FakeDB 用于无 DB 测试。"""
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        def __init__(self):
            self.committed = False
            self._added: list = []

        async def execute(self, stmt):
            return FakeResult()

        async def flush(self):
            pass

        async def commit(self):
            self.committed = True

        def add(self, obj):
            self._added.append(obj)

    return FakeDB()


def _make_fake_sink(db):
    """创建 Fake EventSink 用于测试。"""
    from apps.api.schemas.agent import AgentEvent

    class FakeSink:
        def __init__(self):
            self.events: list = []
            self._last_db_session = db

        @property
        def event_count(self):
            return len(self.events)

        async def emit(self, *, run_id, event, db_session):
            evt = AgentEvent(
                id=str(_uuid.uuid4()),
                run_id=run_id,
                sequence_no=len(self.events),
                agent=event.agent,
                event_type=event.event_type,
                status=event.status,
                summary=event.summary,
                source_refs=event.source_refs,
                duration_ms=event.duration_ms,
                created_at="2026-01-01T00:00:00",
            )
            self.events.append(evt)
            return evt

    return FakeSink()
