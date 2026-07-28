"""Agent Run + SSE 基础设施测试 — 不依赖 C 的完整 Agent。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.schemas.agent import AgentEventDraft  # noqa: E402

# ---- 内存测试替身 ----

class FakeDB:
    """模拟完整 AsyncSession — 支持 execute() 等 SQLAlchemy 方法。"""

    def __init__(self):
        self.events: list[dict] = []
        self.committed = False
        self._seq = {}

    async def execute(self, stmt):
        # 返回类 async Result
        return _FakeResult(self._seq.get("r-default", -1) + 1)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True


class _FakeResult:
    def __init__(self, scalar_val):
        self._scalar = scalar_val

    def scalar_one_or_none(self):
        return self._scalar if self._scalar > -1 else None


# ---- Fixtures ----

@pytest.fixture(autouse=True)
def _patch_repo():
    """用内存实现替换 agent_run repository（避免真实 DB 依赖）。"""
    import apps.api.repositories.agent_run as repo

    _events: list[dict] = {}
    _seqs: dict[str, int] = {}

    async def _get_next_seq(session, run_id):
        seq = _seqs.get(run_id, -1) + 1
        _seqs[run_id] = seq
        return seq

    async def _insert_event(session, *, run_id, sequence_no, agent,
                            event_type, status, summary, source_refs,
                            duration_ms=None, private_payload=None):
        from datetime import UTC, datetime
        evt = {
            "id": f"evt-{sequence_no}", "run_id": run_id,
            "sequence_no": sequence_no, "agent": agent,
            "event_type": event_type, "status": status,
            "summary": summary, "source_refs": source_refs,
            "duration_ms": duration_ms,
            "created_at": datetime.now(UTC).replace(tzinfo=None),
        }
        if run_id not in _events:
            _events[run_id] = []
        _events[run_id].append(evt)
        return type("DBEvent", (), evt)

    repo.get_next_sequence = _get_next_seq
    repo.insert_event = _insert_event
    yield
    # restore not needed (module reload between tests is fine)


# ============================================================
# EventSink 基础
# ============================================================

@pytest.mark.asyncio
async def test_event_sink_persists_before_publish() -> None:
    """事件持久化在发布之前。"""
    from apps.api.services.agent_event_sink import AgentEventSink

    db = FakeDB()
    sink = AgentEventSink()
    draft = AgentEventDraft(
        agent="knowledge", event_type="agent.summary",
        status="running", summary="找到 6 条证据",
    )
    public = await sink.emit(run_id="r-001", event=draft, db_session=db)
    assert db.committed is True
    assert public.agent == "knowledge"
    assert public.summary == "找到 6 条证据"


@pytest.mark.asyncio
async def test_event_sink_sequence_increments() -> None:
    """连续 emit 时 sequence_no 严格递增。"""
    from apps.api.services.agent_event_sink import AgentEventSink

    db = FakeDB()
    sink = AgentEventSink()
    e1 = await sink.emit(run_id="r-002", event=AgentEventDraft(
        agent="coordinator", event_type="run.started", status="running", summary="start",
    ), db_session=db)
    e2 = await sink.emit(run_id="r-002", event=AgentEventDraft(
        agent="knowledge", event_type="agent.summary", status="running", summary="done",
    ), db_session=db)
    assert e1.sequence_no == 0
    assert e2.sequence_no == 1


@pytest.mark.asyncio
async def test_event_sink_concurrent_no_duplicate_seq() -> None:
    """并发 emit 不产生重复 sequence_no。"""
    from apps.api.services.agent_event_sink import AgentEventSink

    db = FakeDB()
    sink = AgentEventSink()

    async def emit_one(i: int):
        return await sink.emit(run_id="r-concurrent", event=AgentEventDraft(
            agent="test", event_type="test", status="running", summary=f"event-{i}",
        ), db_session=db)

    results = []
    for i in range(10):
        results.append(await emit_one(i))
    seqs = [r.sequence_no for r in results]
    assert len(seqs) == len(set(seqs)) == 10


# ============================================================
# 私有字段过滤
# ============================================================

def test_agent_event_draft_no_private_fields() -> None:
    """AgentEventDraft 不含私有字段。"""
    fields = set(AgentEventDraft.model_fields.keys())
    assert "question_private" not in fields
    assert "grade_private" not in fields
    assert "prompt" not in fields


def test_agent_event_public_dto_whitelist() -> None:
    """AgentEvent（公开 DTO）仅含白名单字段。"""
    from apps.api.schemas.agent import AgentEvent

    fields = set(AgentEvent.model_fields.keys())
    allowed = {"id", "run_id", "sequence_no", "agent", "event_type",
               "status", "summary", "source_refs", "duration_ms", "created_at"}
    assert fields == allowed


# ============================================================
# SSE 管理
# ============================================================

@pytest.mark.asyncio
async def test_sse_manager_connect_disconnect() -> None:
    """客户端连接和断线清理。"""
    from apps.api.services.sse_manager import SSEManager

    mgr = SSEManager()
    q = await mgr.connect("r-sse-1")
    assert len(mgr._queues["r-sse-1"]) == 1
    mgr.disconnect("r-sse-1", q)
    assert "r-sse-1" not in mgr._queues


@pytest.mark.asyncio
async def test_sse_manager_publish_to_multiple_clients() -> None:
    """向多个客户端推送同一条事件。"""
    from apps.api.schemas.agent import AgentEvent
    from apps.api.services.sse_manager import SSEManager

    mgr = SSEManager()
    q1 = await mgr.connect("r-multi")
    q2 = await mgr.connect("r-multi")

    evt = AgentEvent(
        id="evt-1", run_id="r-multi", sequence_no=0, agent="test",
        event_type="test", status="running", summary="multi", source_refs=[],
        created_at="2026-01-01T00:00:00",
    )
    await mgr.publish("r-multi", evt)

    msg1 = await asyncio.wait_for(q1.get(), timeout=1)
    msg2 = await asyncio.wait_for(q2.get(), timeout=1)
    assert json.loads(msg1)["summary"] == "multi"
    assert json.loads(msg2)["summary"] == "multi"

    mgr.disconnect("r-multi", q1)
    mgr.disconnect("r-multi", q2)


# ============================================================
# API 路由测试
# ============================================================

def _make_test_app():
    """创建带 session override + ApiError handler 的测试 app。"""
    from apps.api.db.session import get_session
    from apps.api.middleware.trace import TraceMiddleware, get_trace_id
    from apps.api.routers.agent_runs import router as ar_router
    from apps.api.schemas.error import ApiError, ApiErrorResponse

    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    async def _fake_session():
        yield FakeDB()
    app.dependency_overrides[get_session] = _fake_session

    @app.exception_handler(ApiError)
    async def _h(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiErrorResponse(
                code=exc.code, message=exc.message, retryable=exc.retryable,
                trace_id=get_trace_id(), details=exc.details,
            ).model_dump(),
        )
    app.include_router(ar_router, prefix="/api")
    return app


def test_agent_runs_endpoint_requires_auth() -> None:
    """未认证访问 Run 端点返回 401。"""
    from fastapi.testclient import TestClient

    app = _make_test_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/api/agent-runs/some-id")
    assert resp.status_code == 401


def test_retry_endpoint_rejects_unauth() -> None:
    """未认证重试返回 401。"""
    from fastapi.testclient import TestClient

    app = _make_test_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/api/agent-runs/some-id/retry")
    assert resp.status_code == 401
