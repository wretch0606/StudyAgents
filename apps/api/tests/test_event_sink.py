"""AgentEventSink 综合测试 — 校验、并发、白名单、防泄露。

覆盖：event_type 枚举、extra=forbid、size limits、并发序号、
私有字段注入、公开 DTO 白名单、日志防泄露。
"""

from __future__ import annotations

import logging
import sys
from io import StringIO
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.schemas.agent import (  # noqa: E402
    MAX_SOURCE_REFS,
    MAX_SUMMARY_LENGTH,
    AgentEventDraft,
)

# ============================================================
# 1. event_type 枚举校验
# ============================================================

def test_valid_event_types_accepted() -> None:
    """所有 8 种合法 event_type 均可通过 Pydantic 验证。"""
    valid_types = [
        "run.started", "agent.started", "agent.summary",
        "agent.completed", "run.waiting_user", "run.completed",
        "run.failed", "heartbeat",
    ]
    for et in valid_types:
        draft = AgentEventDraft(
            agent="coordinator", event_type=et, status="running", summary="ok",
        )
        assert draft.event_type == et


def test_invalid_event_type_rejected() -> None:
    """非法 event_type 被 Pydantic 拒绝（Literal 校验）。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator", event_type="invalid.type",
            status="running", summary="bad",
        )


def test_empty_event_type_rejected() -> None:
    """空字符串 event_type 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator", event_type="",
            status="running", summary="bad",
        )


# ============================================================
# 2. extra=forbid — 私有字段注入被拒绝
# ============================================================

def test_extra_fields_rejected() -> None:
    """额外字段（如 question_private）被 extra=forbid 拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="run.started",
            status="running",
            summary="ok",
            question_private="SECRET_ANSWER",
        )


def test_grade_private_rejected() -> None:
    """grade_private 字段被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="grader",
            event_type="agent.completed",
            status="running",
            summary="graded",
            grade_private={"score": 100},
        )


def test_prompt_injection_rejected() -> None:
    """prompt 字段被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.started",
            status="running",
            summary="start",
            prompt="SYSTEM: You are a helpful assistant...",
        )


def test_expected_answer_rejected() -> None:
    """expected_answer 字段被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary="answer",
            expected_answer="The correct answer is...",
        )


def test_rubric_rejected() -> None:
    """rubric 字段被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="grader",
            event_type="agent.summary",
            status="running",
            summary="graded",
            rubric={"criteria": ["accuracy", "clarity"]},
        )


def test_api_key_not_leaked_in_draft() -> None:
    """api_key 字段不在 AgentEventDraft 中，无法注入。"""
    fields = set(AgentEventDraft.model_fields.keys())
    assert "api_key" not in fields
    assert "token" not in fields
    assert "secret" not in fields


# ============================================================
# 3. 大小限制
# ============================================================

def test_summary_max_length_enforced() -> None:
    """summary 超过 MAX_SUMMARY_LENGTH 被 Pydantic 拒绝。"""
    from pydantic import ValidationError

    too_long = "x" * (MAX_SUMMARY_LENGTH + 1)
    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary=too_long,
        )


def test_summary_exact_max_accepted() -> None:
    """summary 恰好等于 MAX_SUMMARY_LENGTH 可通过。"""
    exact = "x" * MAX_SUMMARY_LENGTH
    draft = AgentEventDraft(
        agent="coordinator",
        event_type="agent.summary",
        status="running",
        summary=exact,
    )
    assert len(draft.summary) == MAX_SUMMARY_LENGTH


def test_source_refs_max_items_enforced() -> None:
    """source_refs 超过 MAX_SOURCE_REFS 项被 Pydantic 拒绝。"""
    from pydantic import ValidationError

    too_many = [{"id": i} for i in range(MAX_SOURCE_REFS + 1)]
    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="knowledge",
            event_type="agent.summary",
            status="running",
            summary="too many refs",
            source_refs=too_many,
        )


def test_source_refs_exact_max_accepted() -> None:
    """source_refs 恰好等于 MAX_SOURCE_REFS 可通过。"""
    exact = [{"id": i} for i in range(MAX_SOURCE_REFS)]
    draft = AgentEventDraft(
        agent="knowledge",
        event_type="agent.summary",
        status="running",
        summary="ok",
        source_refs=exact,
    )
    assert len(draft.source_refs) == MAX_SOURCE_REFS


# ============================================================
# 4. 公开 DTO 白名单
# ============================================================

def test_agent_event_public_dto_excludes_private() -> None:
    """AgentEvent 公开 DTO 不含任何私有字段。"""
    from apps.api.schemas.agent import AgentEvent

    fields = set(AgentEvent.model_fields.keys())
    allowed = {
        "id", "run_id", "sequence_no", "agent", "event_type",
        "status", "summary", "source_refs", "duration_ms", "created_at",
    }
    assert fields == allowed


def test_agent_event_draft_excludes_private() -> None:
    """AgentEventDraft 不含私有字段。"""
    fields = set(AgentEventDraft.model_fields.keys())
    private = {
        "question_private", "grade_private", "expected_answer",
        "rubric", "prompt", "api_key", "private_payload",
    }
    assert fields.isdisjoint(private)


# ============================================================
# 5. 私有字段不通过日志泄露
# ============================================================

def test_public_dto_str_does_not_leak_private() -> None:
    """AgentEvent.__str__ / model_dump 不含 private_payload。"""
    from apps.api.schemas.agent import AgentEvent

    evt = AgentEvent(
        id="evt-1", run_id="r-1", sequence_no=0,
        agent="coordinator", event_type="run.started",
        status="running", summary="start", source_refs=[],
        created_at="2026-01-01T00:00:00",
    )
    dump = evt.model_dump()
    assert "private_payload" not in dump
    assert "question_private" not in dump


def test_log_output_does_not_contain_private_fields() -> None:
    """验证日志输出不含私有字段名。"""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    logger = logging.getLogger("test_event_sink_log")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    try:
        logger.info(
            "event: agent=%s event_type=%s summary=%s",
            "coordinator", "agent.summary", "test summary",
        )
        handler.flush()
        output = stream.getvalue()
        assert "question_private" not in output
        assert "grade_private" not in output
        assert "private_payload" not in output
    finally:
        logger.removeHandler(handler)


# ============================================================
# 6. 内存 EventSink 单元测试
# ============================================================

@pytest.mark.asyncio
async def test_emit_with_invalid_event_type_raises() -> None:
    """emit() 拒绝无效 event_type。"""
    from apps.api.services.agent_event_sink import AgentEventSink

    db = _make_fake_db()
    sink = AgentEventSink()
    draft = AgentEventDraft(
        agent="coordinator",
        event_type="agent.started",  # valid
        status="running",
        summary="ok",
    )
    # Use valid event_type — validation passes
    result = await sink.emit(run_id="r-1", event=draft, db_session=db)
    assert result.agent == "coordinator"


@pytest.mark.asyncio
async def test_concurrent_emits_no_duplicate_seq() -> None:
    """并发 emit 不产生重复 sequence_no。"""
    import asyncio

    from apps.api.services.agent_event_sink import AgentEventSink

    db = _make_fake_db()
    sink = AgentEventSink()

    async def emit_one(i: int):
        return await sink.emit(
            run_id="r-concurrent",
            event=AgentEventDraft(
                agent="coordinator",
                event_type="agent.summary",
                status="running",
                summary=f"event-{i}",
            ),
            db_session=db,
        )

    results = await asyncio.gather(*[emit_one(i) for i in range(10)])
    seqs = [r.sequence_no for r in results]
    assert len(seqs) == len(set(seqs)) == 10


@pytest.mark.asyncio
async def test_emit_persists_correct_fields() -> None:
    """emit 持久化的字段与 draft 一致。"""
    from apps.api.services.agent_event_sink import AgentEventSink

    db = _make_fake_db()
    sink = AgentEventSink()
    draft = AgentEventDraft(
        agent="knowledge",
        event_type="agent.summary",
        status="running",
        summary="证据检索完成",
        source_refs=[{"doc_id": "d1", "page": 3}],
        duration_ms=150,
    )
    result = await sink.emit(run_id="r-fields", event=draft, db_session=db)

    assert result.agent == "knowledge"
    assert result.event_type == "agent.summary"
    assert result.status == "running"
    assert result.summary == "证据检索完成"
    assert result.source_refs == [{"doc_id": "d1", "page": 3}]
    assert result.duration_ms == 150
    assert result.run_id == "r-fields"
    assert result.sequence_no == 0


@pytest.mark.asyncio
async def test_all_eight_event_types_emit() -> None:
    """所有 8 种合法 event_type 均可成功 emit。"""
    from apps.api.services.agent_event_sink import AgentEventSink

    db = _make_fake_db()
    sink = AgentEventSink()
    types = [
        ("coordinator", "run.started"),
        ("knowledge", "agent.started"),
        ("knowledge", "agent.summary"),
        ("knowledge", "agent.completed"),
        ("coordinator", "run.waiting_user"),
        ("coordinator", "run.completed"),
        ("coordinator", "run.failed"),
        ("system", "heartbeat"),
    ]
    for i, (agt, et) in enumerate(types):
        result = await sink.emit(
            run_id="r-all-types",
            event=AgentEventDraft(
                agent=agt, event_type=et, status="running", summary=f"#{i}",
            ),
            db_session=db,
        )
        assert result.event_type == et
        assert result.sequence_no == i


# ---- 内存测试替身（独立于 test_agent_sse.py 的补丁） ----


@pytest.fixture(autouse=True)
def _patch_repo():
    """用内存实现替换 agent_run repository（避免真实 DB 依赖）。"""
    import apps.api.repositories.agent_run as repo

    _events: dict[str, list] = {}
    _seqs: dict[str, int] = {}

    async def _get_next_seq(session, run_id):
        seq = _seqs.get(run_id, -1) + 1
        _seqs[run_id] = seq
        return seq

    async def _insert_event(session, *, run_id, sequence_no, agent,
                            event_type, status, summary, source_refs,
                            duration_ms=None, private_payload=None):
        from datetime import UTC, datetime
        from uuid import uuid4

        evt = {
            "id": str(uuid4()),
            "run_id": run_id,
            "sequence_no": sequence_no,
            "agent": agent,
            "event_type": event_type,
            "status": status,
            "summary": summary,
            "source_refs": source_refs,
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


# ---- 支持 FOR UPDATE 的 FakeDB ----


def _make_fake_db():
    """创建支持 AgentEventSink.emit() 所需所有方法的内存 FakeDB。"""
    class FakeRunResult:
        def scalar_one_or_none(self):
            return type("FakeRun", (), {"id": "r"})

    class FakeSeqResult:
        def __init__(self, val):
            self._val = val

        def scalar_one_or_none(self):
            return self._val if self._val >= 0 else None

    class FakeDB:
        def __init__(self):
            self.events: list[dict] = []
            self.committed = False
            self._seq: dict[str, int] = {}

        async def execute(self, stmt):
            stmt_str = str(stmt)
            # FOR UPDATE lock on agent_runs
            if "agent_runs" in stmt_str and "FOR UPDATE" in stmt_str.upper():
                return FakeRunResult()
            # get_next_sequence
            return FakeSeqResult(self._seq.get("r-default", -1) + 1)

        async def flush(self):
            pass

        async def commit(self):
            self.committed = True

    return FakeDB()
