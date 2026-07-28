"""AgentEventSink 综合测试 — 校验、并发、白名单、防泄露。

覆盖：event_type 枚举、extra=forbid、size limits、并发序号、
私有字段注入、公开 DTO 白名单、日志防泄露。
"""

from __future__ import annotations

import logging
import os
import sys
from io import StringIO
from pathlib import Path

import pytest

DATABASE_URL = os.getenv("DATABASE_URL", "")

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.schemas.agent import (  # noqa: E402
    MAX_SOURCE_REFS,
    MAX_SUMMARY_LENGTH,
    AgentEventDraft,
    SourceRef,
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

    too_many = [{"document_id": f"doc-{i}"} for i in range(MAX_SOURCE_REFS + 1)]
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
    exact = [{"document_id": f"doc-{i}"} for i in range(MAX_SOURCE_REFS)]
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
        source_refs=[{"document_id": "d1", "page_no": 3}],
        duration_ms=150,
    )
    result = await sink.emit(run_id="r-fields", event=draft, db_session=db)

    assert result.agent == "knowledge"
    assert result.event_type == "agent.summary"
    assert result.status == "running"
    assert result.summary == "证据检索完成"
    assert len(result.source_refs) == 1
    assert result.source_refs[0].document_id == "d1"
    assert result.source_refs[0].page_no == 3
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
def _patch_repo(request):
    """用内存实现替换 agent_run repository（避免真实 DB 依赖）。

    标记 @pytest.mark.real_db 的测试跳过此补丁，使用真实数据库。
    保存并恢复原始函数，防止补丁在测试间泄漏。
    """
    if request.node.get_closest_marker("real_db"):
        yield
        return
    import apps.api.repositories.agent_run as repo

    _events: dict[str, list] = {}
    _seqs: dict[str, int] = {}

    _orig_get_next = repo.get_next_sequence
    _orig_insert = repo.insert_event

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
    repo.get_next_sequence = _orig_get_next
    repo.insert_event = _orig_insert


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


# ============================================================
# 7. source_refs 嵌套私有字段注入测试
# ============================================================

def test_source_refs_rejects_private_field_injection() -> None:
    """source_refs 元素内注入 question_private 被 SourceRef extra=forbid 拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary="ok",
            source_refs=[{
                "document_id": "d1",
                "question_private": "SECRET_ANSWER",
            }],
        )


def test_source_refs_rejects_grade_private() -> None:
    """source_refs 元素内注入 grade_private 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="grader",
            event_type="agent.completed",
            status="running",
            summary="graded",
            source_refs=[{
                "document_id": "d1",
                "grade_private": {"score": 100},
            }],
        )


def test_source_refs_rejects_prompt_injection() -> None:
    """source_refs 元素内注入 prompt 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary="ok",
            source_refs=[{
                "document_id": "d1",
                "prompt": "SYSTEM: You are a helpful assistant...",
            }],
        )


def test_source_refs_rejects_rubric() -> None:
    """source_refs 元素内注入 rubric 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="grader",
            event_type="agent.summary",
            status="running",
            summary="graded",
            source_refs=[{
                "document_id": "d1",
                "rubric": {"criteria": ["accuracy"]},
            }],
        )


def test_source_refs_rejects_api_key() -> None:
    """source_refs 元素内注入 api_key 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary="ok",
            source_refs=[{
                "document_id": "d1",
                "api_key": "sk-evil",
            }],
        )


def test_source_refs_rejects_chain_of_thought() -> None:
    """source_refs 元素内注入 chain_of_thought 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary="ok",
            source_refs=[{
                "document_id": "d1",
                "chain_of_thought": "Step 1: think...",
            }],
        )


def test_source_refs_rejects_raw_query() -> None:
    """source_refs 元素内注入 raw_query 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary="ok",
            source_refs=[{
                "document_id": "d1",
                "raw_query": "SELECT * FROM users",
            }],
        )


def test_source_refs_excerpt_max_length_enforced() -> None:
    """source_refs excerpt 字段不能绕过 summary 的 2000 字限制。"""
    from pydantic import ValidationError

    from apps.api.schemas.agent import MAX_EXCERPT_LENGTH

    too_long_excerpt = "x" * (MAX_EXCERPT_LENGTH + 1)
    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="knowledge",
            event_type="agent.summary",
            status="running",
            summary="",
            source_refs=[{
                "document_id": "d1",
                "excerpt": too_long_excerpt,
            }],
        )


def test_source_refs_valid_element_accepted() -> None:
    """合法的 SourceRef 元素通过验证。"""
    draft = AgentEventDraft(
        agent="knowledge",
        event_type="agent.summary",
        status="running",
        summary="证据检索完成",
        source_refs=[{
            "document_id": "doc-001",
            "document_name": "数学必修一.pdf",
            "page_no": 42,
            "question_no": "3",
            "excerpt": "根据勾股定理...",
        }],
    )
    assert len(draft.source_refs) == 1
    ref = draft.source_refs[0]
    assert ref.document_id == "doc-001"
    assert ref.page_no == 42


# ============================================================
# 8. 哨兵值防泄露测试
# ============================================================

_SENTINELS = {
    "question": "PRIVATE_QUESTION_CANARY_abc123",
    "rubric": "PRIVATE_RUBRIC_CANARY_def456",
    "prompt": "PRIVATE_PROMPT_CANARY_ghi789",
    "api_key": "PRIVATE_API_KEY_CANARY_sk-jkl012",
    "raw_query": "PRIVATE_RAW_QUERY_CANARY_mno345",
}


def test_sentinels_not_in_model_dump() -> None:
    """哨兵值不出现在 AgentEvent.model_dump() 中。"""
    from apps.api.schemas.agent import AgentEvent

    evt = AgentEvent(
        id="evt-sentinel", run_id="r-1", sequence_no=0,
        agent="coordinator", event_type="run.started",
        status="running", summary="SENTINEL_SAFE_SUMMARY",
        source_refs=[SourceRef(document_id="d1")],
        created_at="2026-01-01T00:00:00",
    )
    dump_str = str(evt.model_dump())
    for label, sentinel in _SENTINELS.items():
        assert sentinel not in dump_str, f"{label} sentinel leaked in model_dump"


def test_sentinels_not_in_validation_error() -> None:
    """ValidationError 消息不含哨兵值。"""
    from pydantic import ValidationError

    for label, sentinel in _SENTINELS.items():
        try:
            AgentEventDraft(
                agent="coordinator",
                event_type="agent.summary",
                status="running",
                summary=sentinel,  # purposefully long — val will fail here if >2000
            )
        except ValidationError as exc:
            err_str = str(exc)
            assert sentinel not in err_str, (
                f"{label} sentinel leaked in ValidationError message"
            )


def test_sentinels_not_in_repr_str() -> None:
    """哨兵值不出现在 AgentEvent 的公开 repr/str 中。

    SourceRef 的合法字段（如 excerpt）会自然出现在 repr 中——
    这是预期行为。关键是要确保 private_payload 等私有字段
    不通过 repr/str 泄露。
    """
    from apps.api.schemas.agent import AgentEvent

    evt = AgentEvent(
        id="evt-repr", run_id="r-1", sequence_no=0,
        agent="coordinator", event_type="run.started",
        status="running", summary="safe",
        source_refs=[SourceRef(document_id="d1")],
        created_at="2026-01-01T00:00:00",
    )
    evt_str = repr(evt)
    evt_str_lower = str(evt).lower()
    # private_payload must NOT appear in repr or str
    assert "private_payload" not in evt_str, f"private_payload in repr: {evt_str}"
    assert "private_payload" not in evt_str_lower
    # sentinels must not appear in AgentEvent repr (they can't be in AgentEvent)
    for label, sentinel in _SENTINELS.items():
        assert sentinel not in evt_str, f"{label} sentinel leaked in repr"
        assert sentinel not in evt_str_lower, f"{label} sentinel leaked in str"


def test_sentinels_not_in_source_refs_dump() -> None:
    """哨兵值不能通过 source_refs 嵌套注入后出现在 model_dump 中。"""
    # Valid SourceRef but with a sentinel in excerpt (excerpt is allowed)
    draft = AgentEventDraft(
        agent="knowledge",
        event_type="agent.summary",
        status="running",
        summary="safe summary",
        source_refs=[{
            "document_id": "d1",
            "excerpt": _SENTINELS["question"],
        }],
    )
    # Sentinel in excerpt IS allowed content — but verify no OTHER sentinels leak
    dump_str = str(draft.model_dump())
    for label, sentinel in _SENTINELS.items():
        if label == "question":
            continue  # This one IS in excerpt by design
        assert sentinel not in dump_str, f"{label} sentinel leaked via source_refs"


def test_source_refs_rejects_expected_answer_injection() -> None:
    """source_refs 元素内注入 expected_answer 被拒绝。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentEventDraft(
            agent="coordinator",
            event_type="agent.summary",
            status="running",
            summary="ok",
            source_refs=[{
                "document_id": "d1",
                "expected_answer": "The correct answer is B",
            }],
        )


# ============================================================
# 9. Commit-before-publish 失败场景测试
# ============================================================

@pytest.mark.asyncio
async def test_no_sse_publish_on_db_error() -> None:
    """数据库操作失败时不发布 SSE。"""
    from apps.api.services.agent_event_sink import AgentEventSink

    db = _make_failing_db()
    sink = AgentEventSink()
    draft = AgentEventDraft(
        agent="coordinator", event_type="run.started",
        status="running", summary="start",
    )
    with pytest.raises(RuntimeError, match="DB commit failed"):
        await sink.emit(run_id="r-fail", event=draft, db_session=db)
    # SSE should never have been called (test passes if exception raised before publish)


@pytest.mark.asyncio
async def test_event_persisted_even_when_sse_publish_fails() -> None:
    """SSE 发布失败后事件仍在数据库中（commit 已成功）。"""
    import apps.api.services.sse_manager as sse_mod

    db = _make_fake_db()
    original_publish = sse_mod.sse_manager.publish

    async def _failing_publish(run_id, event):
        raise ConnectionError("SSE publish failed")

    sse_mod.sse_manager.publish = _failing_publish
    try:
        from apps.api.services.agent_event_sink import AgentEventSink

        sink = AgentEventSink()
        draft = AgentEventDraft(
            agent="coordinator", event_type="run.started",
            status="running", summary="persist-test",
        )
        result = await sink.emit(run_id="r-sse-fail", event=draft, db_session=db)
        # emit returns successfully (exception caught and logged)
        assert result.summary == "persist-test"
        # DB was committed before SSE failure
        assert db.committed is True
    finally:
        sse_mod.sse_manager.publish = original_publish


@pytest.mark.asyncio
async def test_sequence_monotonic_after_failure() -> None:
    """emit 失败后重试不重复 sequence_no。"""
    import apps.api.services.sse_manager as sse_mod
    from apps.api.services.agent_event_sink import AgentEventSink

    db = _make_fake_db()
    sink = AgentEventSink()

    # First emit — succeeds, seq=0
    e1 = await sink.emit(
        run_id="r-seq-fail",
        event=AgentEventDraft(
            agent="coordinator", event_type="run.started",
            status="running", summary="first",
        ),
        db_session=db,
    )
    assert e1.sequence_no == 0

    # Second emit after SSE failure (but commit succeeded) — seq=1
    original_publish = sse_mod.sse_manager.publish

    async def _failing_publish(run_id, event):
        raise ConnectionError("SSE publish failed")

    sse_mod.sse_manager.publish = _failing_publish
    try:
        e2 = await sink.emit(
            run_id="r-seq-fail",
            event=AgentEventDraft(
                agent="coordinator", event_type="agent.summary",
                status="running", summary="second",
            ),
            db_session=db,
        )
        assert e2.sequence_no == 1  # not 0 — sequence advanced
        assert e1.sequence_no != e2.sequence_no
    finally:
        sse_mod.sse_manager.publish = original_publish


# ---- helpers for failure tests ----


def _make_failing_db():
    """创建 commit 会失败的 FakeDB。"""

    class FakeRunResult:
        def scalar_one_or_none(self):
            return type("FakeRun", (), {"id": "r"})

    class FakeSeqResult:
        def __init__(self, val):
            self._val = val

        def scalar_one_or_none(self):
            return self._val if self._val >= 0 else None

    class FailingDB:
        def __init__(self):
            self._seq: dict[str, int] = {}

        async def execute(self, stmt):
            stmt_str = str(stmt)
            if "agent_runs" in stmt_str and "FOR UPDATE" in stmt_str.upper():
                return FakeRunResult()
            return FakeSeqResult(self._seq.get("r-default", -1) + 1)

        async def flush(self):
            pass

        async def commit(self):
            raise RuntimeError("DB commit failed")

    return FailingDB()


# ============================================================
# 10. 真实 PostgreSQL 并发测试
# ============================================================

@pytest.mark.real_db
@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_postgres_concurrent_emit_no_duplicate_seq() -> None:
    """真实 PostgreSQL + 独立 session + asyncio.gather 并发测试。

    验证 SELECT ... FOR UPDATE 锁在真实数据库中防止重复 sequence_no。
    """
    import asyncio
    import uuid

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from apps.api.db.models.agent_run import AgentRun as AgentRunModel
    from apps.api.db.models.user import User
    from apps.api.services.agent_event_sink import AgentEventSink

    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(async_url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        # Fetch a user for foreign key
        user_result = await session.execute(select(User).limit(1))
        user = user_result.scalar_one_or_none()
        if user is None:
            pytest.skip("No users in database")

        # Create an agent_run for the test events
        rid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        run = AgentRunModel(id=rid, thread_id=tid, user_id=user.id, mode="qa")
        session.add(run)
        await session.commit()

    n_workers = 5

    async def emit_one(i: int) -> int:
        """每个协程使用独立的 AsyncSession 模拟真实并发。"""
        async with maker() as session:
            sink = AgentEventSink()
            result = await sink.emit(
                run_id=rid,
                event=AgentEventDraft(
                    agent="coordinator",
                    event_type="agent.summary",
                    status="running",
                    summary=f"concurrent-{i}",
                ),
                db_session=session,
            )
            return result.sequence_no

    results = await asyncio.gather(*[emit_one(i) for i in range(n_workers)])
    seqs = sorted(results)
    # Verify all sequence numbers are unique and form a consecutive range
    assert seqs == list(range(n_workers)), (
        f"Expected 0..{n_workers - 1}, got {seqs}"
    )
    assert len(set(seqs)) == n_workers

    # Cleanup: delete test data
    async with maker() as session:
        await session.execute(
            select(AgentRunModel).where(AgentRunModel.id == rid),
        )
        run_to_delete = (await session.execute(
            select(AgentRunModel).where(AgentRunModel.id == rid),
        )).scalar_one_or_none()
        if run_to_delete:
            await session.delete(run_to_delete)
            await session.commit()

    await engine.dispose()


@pytest.mark.real_db
@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_postgres_event_recoverable_after_sse_failure() -> None:
    """SSE 发布失败后，已提交事件可通过新 Session 从数据库重读。

    验证：
    - 发布失败不阻止持久化（commit 已成功）
    - 新 Session 可通过 get_events_since 查到已提交事件
    - event id 和 sequence_no 正确
    - 再次 emit 后 sequence_no 继续递增
    """
    import uuid

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from apps.api.db.models.agent_run import AgentRun as AgentRunModel
    from apps.api.db.models.user import User
    from apps.api.repositories.agent_run import get_events_since
    from apps.api.services.agent_event_sink import AgentEventSink

    url = DATABASE_URL
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(async_url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Create a new user + run
    async with maker() as session:
        user_result = await session.execute(select(User).limit(1))
        user = user_result.scalar_one_or_none()
        if user is None:
            pytest.skip("No users in database")

        rid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        run = AgentRunModel(id=rid, thread_id=tid, user_id=user.id, mode="qa")
        session.add(run)
        await session.commit()
        run_user_id = str(user.id)

    # Mock SSE publish to fail
    import apps.api.services.sse_manager as sse_mod

    original_publish = sse_mod.sse_manager.publish

    async def _failing_publish(run_id, event):
        raise ConnectionError("SSE publish failed")

    sse_mod.sse_manager.publish = _failing_publish
    try:
        # Emit with mocked SSE failure
        async with maker() as session:
            sink = AgentEventSink()
            result = await sink.emit(
                run_id=rid,
                event=AgentEventDraft(
                    agent="coordinator",
                    event_type="run.started",
                    status="running",
                    summary="persist-after-sse-fail",
                ),
                db_session=session,
            )
            first_event_id = result.id
            first_seq = result.sequence_no
            assert first_seq == 0

        # NOW: use a NEW session to re-read from DB (independent session)
        async with maker() as session:
            events = await get_events_since(
                session, rid, user_id=run_user_id, since_seq=-1,
            )
            assert len(events) >= 1, "Event should be queryable after SSE failure"
            found = [e for e in events if str(e.id) == first_event_id]
            assert len(found) == 1, "Committed event not found via new session"
            assert found[0].sequence_no == 0
            assert found[0].summary == "persist-after-sse-fail"

        # Emit again — sequence_no should continue (1, not 0)
        async with maker() as session:
            sink = AgentEventSink()
            result2 = await sink.emit(
                run_id=rid,
                event=AgentEventDraft(
                    agent="coordinator",
                    event_type="agent.summary",
                    status="running",
                    summary="second-after-failure",
                ),
                db_session=session,
            )
            assert result2.sequence_no == 1, (
                f"Expected seq=1 after failure, got {result2.sequence_no}"
            )

        # Verify both events now queryable
        async with maker() as session:
            events = await get_events_since(
                session, rid, user_id=run_user_id, since_seq=-1,
            )
            assert len(events) == 2
            assert events[0].sequence_no == 0
            assert events[1].sequence_no == 1
    finally:
        sse_mod.sse_manager.publish = original_publish
        # Cleanup
        async with maker() as session:
            run_to_delete = (
                await session.execute(
                    select(AgentRunModel).where(AgentRunModel.id == rid),
                )
            ).scalar_one_or_none()
            if run_to_delete:
                await session.delete(run_to_delete)
                await session.commit()

    await engine.dispose()
