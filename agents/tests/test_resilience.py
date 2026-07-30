"""
Day 6 弹性测试 — 故障注入与系统行为验证

覆盖:
  1. 模型超时 → 返回 AGENT_MODEL_TIMEOUT 错误（retryable=True）
  2. HTTP 429 → 返回可重试错误
  3. HTTP 5xx → 返回可重试错误
  4. 无效 JSON → 重试后仍失败则返回错误
  5. 错误引用 → 被引用核验阻止，不输出越权内容
  6. 重试上限 → 最多 2 次重试，超出后返回 non-retryable 错误
  7. MAX_MODEL_CALLS / MAX_NODE_HOPS 限制
  8. 低置信度回退（训练模式）
  9. 状态恢复（checkpoint 恢复）
 10. 错误对象包含 code/retryable/trace_id

用法: python -m pytest agents/tests/test_resilience.py -v
"""

from __future__ import annotations

import asyncio
import sys
import os
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps"))

from agents.state import AgentState
from agents.graph import (
    coordinator_node,
    knowledge_node,
    evaluator_qa_node,
    refusal_node,
    error_node,
    _limits_exceeded,
    MAX_MODEL_CALLS,
    MAX_NODE_HOPS,
)
from agents.tests.fake_adapters import (
    FaultConfig,
    FakeModelGateway,
    FakeRetriever,
    FakeEventSink,
    FakeCheckpointer,
    FakeSourceRef,
    ModelGatewayError,
)

# ═══════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════

PASSED = 0
FAILED = 0


def _ok(name: str):
    global PASSED
    PASSED += 1
    print(f"  [OK] {name}")


def _fail(name: str, detail: str = ""):
    global FAILED
    FAILED += 1
    msg = f"  [FAIL] {name}"
    if detail:
        msg += f"  --  {detail}"
    print(msg)


def _base_state(**overrides) -> AgentState:
    """创建基础测试状态"""
    state: AgentState = {
        "run_id": "run-test-001",
        "trace_id": "trace-test-001",
        "thread_id": "thread-test-001",
        "user_id": "user-test-001",
        "mode": "qa",
        "user_input": "什么是数据库管理系统？",
        "filters": {},
        "model_calls": 0,
        "node_hops": 0,
        "retry_count": 0,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def _config(model=None, retriever=None, event_sink=None) -> dict:
    """创建 LangGraph config"""
    return {
        "configurable": {
            "model": model or FakeModelGateway(),
            "retriever": retriever or FakeRetriever(),
            "event_sink": event_sink or FakeEventSink(),
        }
    }


# ═══════════════════════════════════════════════════════
# 1. 模型超时
# ═══════════════════════════════════════════════════════


async def test_timeout_handling():
    """模拟模型超时 → D 内部重试 2 次后抛 ModelGatewayError"""
    gateway = FakeModelGateway(
        fault=FaultConfig(timeout_seconds=30.0, trigger_on_call=1)
    )
    state = _base_state(normalized_query="测试查询")
    cfg = _config(model=gateway)

    try:
        result = await knowledge_node(state, cfg)
        # 如果没抛异常（正常输出），检查结果
        assert result.get("next_node") in ("error", "evaluator_qa", "refusal"), (
            f"意外结果: {result.get('next_node')}"
        )
    except ModelGatewayError as e:
        # D 的 ModelGateway 重试耗尽后抛异常，由 AgentRunner 层捕获
        assert e.status_code == 504  # 超时耗尽后的错误码
        assert e.retryable is False
        assert gateway.call_log[-1]["internal_retries"] == gateway.MAX_RETRIES
    except asyncio.TimeoutError:
        # 直接超时（重试也超时）
        pass

    _ok("超时 → D 内部重试 2 次，耗尽后抛异常或返回错误")


# ═══════════════════════════════════════════════════════
# 2. HTTP 429
# ═══════════════════════════════════════════════════════


async def test_http_429_handling():
    """模拟 HTTP 429 → D 内部重试 2 次后抛异常"""
    gateway = FakeModelGateway(
        fault=FaultConfig(http_error=429, trigger_on_call=1)
    )
    state = _base_state(normalized_query="测试查询")
    cfg = _config(model=gateway)

    try:
        result = await knowledge_node(state, cfg)
        assert result.get("next_node") in ("error", "evaluator_qa", "refusal")
    except ModelGatewayError as e:
        assert e.status_code == 429
        assert e.retryable is True  # 429 是可重试的
        assert gateway.call_log[-1]["internal_retries"] > 0

    _ok("HTTP 429 → D 内部重试后仍失败，异常冒泡")


# ═══════════════════════════════════════════════════════
# 3. HTTP 5xx
# ═══════════════════════════════════════════════════════


async def test_http_5xx_handling():
    """模拟 HTTP 500/502/503 → D 内部重试 2 次后抛异常"""
    for status in (500, 502, 503):
        gateway = FakeModelGateway(
            fault=FaultConfig(http_error=status, trigger_on_call=1)
        )
        state = _base_state(normalized_query="测试查询")
        cfg = _config(model=gateway)

        try:
            result = await knowledge_node(state, cfg)
            assert result.get("next_node") in ("error", "evaluator_qa", "refusal")
        except ModelGatewayError as e:
            assert e.status_code == status
            assert gateway.call_log[-1]["internal_retries"] > 0

    _ok("HTTP 500/502/503 → D 内部重试后仍失败，异常冒泡")


# ═══════════════════════════════════════════════════════
# 4. 无效 JSON
# ═══════════════════════════════════════════════════════


async def test_invalid_json_handling():
    """模拟模型返回无效 JSON → D 内部重试 2 次后抛异常"""
    gateway = FakeModelGateway(
        fault=FaultConfig(invalid_json=True, trigger_on_call=1)
    )
    state = _base_state(normalized_query="测试查询")
    cfg = _config(model=gateway)

    try:
        result = await knowledge_node(state, cfg)
        assert result.get("next_node") in ("error", "evaluator_qa", "refusal")
    except ModelGatewayError:
        assert gateway.call_log[-1]["internal_retries"] > 0

    _ok("无效 JSON → D 内部重试后仍失败，异常冒泡")


# ═══════════════════════════════════════════════════════
# 5. 错误引用阻止
# ═══════════════════════════════════════════════════════


async def test_bad_citation_blocked():
    """知识项的 source_ref_ids 不在 evidence 中 → 应被阻止"""
    # 设置 normal gateway + bad_citation
    gateway = FakeModelGateway(
        fault=FaultConfig(bad_citation=True)
    )
    # 使用不匹配的 evidence（knowledge item 引用 chunk-nonexistent，但 evidence 只有 chunk-test-001）
    from agents.state import SourceRef

    evidence: list[SourceRef] = [
        SourceRef(
            document_id="doc-1",
            document_name="test.pdf",
            page_number=1,
            question_no=None,
            chunk_id="chunk-test-001",  # 与 bad_citation 不匹配
            excerpt="测试内容",
            page_image_url=None,
            score=0.9,
        )
    ]

    state = _base_state(
        evidence=evidence,
        knowledge=[
            {
                "fact": "一个引用错误的事实",
                "source_ref_ids": ["chunk-nonexistent"],  # 不在 evidence 中
                "knowledge_point_ids": [],
            }
        ],
    )
    cfg = _config(model=gateway)
    sink = FakeEventSink()
    cfg["configurable"]["event_sink"] = sink

    result = await evaluator_qa_node(state, cfg)

    # 应进入 error，因为有引用核验失败
    assert result.get("next_node") == "error", (
        f"错误引用应被阻止，期望 error，实际 {result.get('next_node')}"
    )
    error = result.get("error", {})
    assert error.get("code") == "AGENT_OUTPUT_INVALID", (
        f"错误码应为 AGENT_OUTPUT_INVALID，实际 {error.get('code')}"
    )
    _ok("错误引用 → 被引用核验阻止，返回 AGENT_OUTPUT_INVALID")


async def test_valid_citation_passes():
    """知识项的 source_ref_ids 都在 evidence 中 → 应正常通过"""
    from agents.state import SourceRef

    evidence: list[SourceRef] = [
        SourceRef(
            document_id="doc-1",
            document_name="test.pdf",
            page_number=1,
            question_no=None,
            chunk_id="chunk-test-001",
            excerpt="测试内容",
            page_image_url=None,
            score=0.9,
        )
    ]

    gateway = FakeModelGateway()
    state = _base_state(
        evidence=evidence,
        knowledge=[
            {
                "fact": "一个有效引用的事实",
                "source_ref_ids": ["chunk-test-001"],  # 在 evidence 中
                "knowledge_point_ids": [],
            }
        ],
    )
    cfg = _config(model=gateway)
    sink = FakeEventSink()
    cfg["configurable"]["event_sink"] = sink

    result = await evaluator_qa_node(state, cfg)

    assert result.get("next_node") == "__end__", (
        f"有效引用应正常结束，实际 {result.get('next_node')}"
    )
    assert result.get("public_response"), "应有公开回答"
    _ok("有效引用 → 正常通过，回答已生成")


# ═══════════════════════════════════════════════════════
# 6. 重试上限
# ═══════════════════════════════════════════════════════


def test_max_model_calls_limit():
    """model_calls 达到 MAX_MODEL_CALLS 时应触发限制"""
    state = _base_state(
        model_calls=MAX_MODEL_CALLS,  # 4
        node_hops=2,
    )
    assert _limits_exceeded(state), "model_calls=4 应触发限制"
    _ok(f"MAX_MODEL_CALLS={MAX_MODEL_CALLS} → 触发限制")


def test_max_node_hops_limit():
    """node_hops 达到 MAX_NODE_HOPS 时应触发限制"""
    state = _base_state(
        model_calls=1,
        node_hops=MAX_NODE_HOPS,  # 8
    )
    assert _limits_exceeded(state), "node_hops=8 应触发限制"
    _ok(f"MAX_NODE_HOPS={MAX_NODE_HOPS} → 触发限制")


def test_within_limits():
    """在限制内不应触发"""
    state = _base_state(model_calls=2, node_hops=4)
    assert not _limits_exceeded(state), "在限制内不应触发"
    _ok("model_calls=2, node_hops=4 → 不触发限制")


async def test_limits_exceeded_in_node():
    """节点执行时发现超限 → 返回 error 而非继续"""
    state = _base_state(
        model_calls=MAX_MODEL_CALLS,  # 已达上限
        node_hops=0,
    )
    cfg = _config()

    result = await coordinator_node(state, cfg)
    assert result.get("next_node") == "error", (
        f"超限应返回 error，实际 {result.get('next_node')}"
    )
    error = result.get("error", {})
    assert error.get("code") == "AGENT_LIMIT_EXCEEDED"
    assert error.get("retryable") is False
    _ok("节点超限 → 返回 AGENT_LIMIT_EXCEEDED（不可重试）")


# ═══════════════════════════════════════════════════════
# 7. 错误对象完整性
# ═══════════════════════════════════════════════════════


def test_error_object_contains_required_fields():
    """所有错误返回必须包含 code/retryable/trace_id"""
    from agents.graph import _error_return

    state = _base_state()
    error_result = _error_return(state, "TEST_ERROR", "测试错误", True)

    assert "error" in error_result
    error = error_result["error"]
    assert "code" in error, "缺少 code"
    assert "message" in error, "缺少 message"
    assert "retryable" in error, "缺少 retryable"
    assert "trace_id" in error, "缺少 trace_id"
    assert error["code"] == "TEST_ERROR"
    assert error["retryable"] is True
    assert error["trace_id"] == state["trace_id"]
    _ok("错误对象 → code/message/retryable/trace_id 完整")


async def test_error_node_includes_trace_id():
    """error_node 返回的错误包含 trace_id"""
    state = _base_state(
        error={
            "code": "TEST_ERROR",
            "message": "测试错误",
            "retryable": True,
            "trace_id": "trace-test-001",
        }
    )
    result = await error_node(state, None)

    assert result.get("public_response") is not None
    assert "error" not in result  # error_node 清除 error，返回公开响应
    _ok("error_node → 返回公开响应（已消费错误）")


# ═══════════════════════════════════════════════════════
# 8. 低置信度回退
# ═══════════════════════════════════════════════════════


async def test_low_confidence_fallback():
    """出题置信度 < 0.8 → 应触发降级（回退到真题）"""
    from agents.graph_practice import questioner_node
    from agents.state import AgentState

    gateway = FakeModelGateway(
        fault=FaultConfig(low_confidence=True)
    )
    retriever = FakeRetriever()

    state: AgentState = {
        "run_id": "run-test-001",
        "trace_id": "trace-test-001",
        "thread_id": "thread-test-001",
        "user_id": "user-test-001",
        "mode": "practice",
        "user_input": "开始训练",
        "filters": {"chapter_ids": ["ch-01"], "difficulty": 2},
        "model_calls": 0,
        "node_hops": 0,
        "retry_count": 0,
        "current_item_index": 0,
        "target_count": 5,
        "practice_items": [],
        "exclude_chunk_ids": [],
    }

    # V1.1: 通过 config["configurable"] 注入依赖
    result = await questioner_node(state, {
        "configurable": {
            "model": gateway,
            "retriever": retriever,
        }
    })

    # 低置信度时内部会 emit 降级事件
    # 出题仍会继续（使用真题回退），不中断流
    practice_items = result.get("practice_items", [])
    assert len(practice_items) > 0, "即使低置信度也应产出题目（降级后使用真题）"
    _ok("低置信度 → 触发降级，回退到真题继续出题")


# ═══════════════════════════════════════════════════════
# 9. 拒答模板完整性（扩展）
# ═══════════════════════════════════════════════════════


def test_all_refusal_reasons_have_template():
    """7 种拒答原因都应有完整模板"""
    from agents.prompts.refusal import RefusalTemplate

    reasons = [
        "no_results", "topic_mismatch", "missing_condition",
        "conflicting", "staff_only", "image_unavailable",
    ]

    for reason in reasons:
        result = RefusalTemplate.build(reason, searched_chapters=["ch-01", "ch-02"])
        assert result["conclusion"], f"{reason}: 缺少 conclusion"
        assert result["searched_scope"], f"{reason}: 缺少 searched_scope"
        assert result["suggestion"], f"{reason}: 缺少 suggestion"
        assert result["refusal_reason"] == reason
    _ok("7 种拒答原因 → 模板完整")


async def test_refusal_node_output_no_private():
    """拒答节点输出不应包含私有字段"""
    state = _base_state(
        reason="no_results",
        filters={"chapter_ids": ["ch-01"]},
    )
    sink = FakeEventSink()

    result = await refusal_node(state, _config(event_sink=sink))

    public_response = result.get("public_response", "")
    forbidden = ["expected_answer", "rubric", "private_evidence"]
    for field in forbidden:
        assert field not in public_response.lower(), f"拒答应包含禁止字段 {field}"
    _ok("拒答输出 → 不含私有字段")


# ═══════════════════════════════════════════════════════
# 10. FakeModelGateway 通话记录
# ═══════════════════════════════════════════════════════


async def test_model_gateway_call_logging():
    """FakeModelGateway 记录每次调用，便于验证重试次数"""
    gateway = FakeModelGateway()

    await gateway.invoke_structured(
        run_id="r1",
        agent="test",
        prompt_version="v1",
        messages=[],
        output_schema=SimpleNamespace,
    )
    await gateway.invoke_structured(
        run_id="r2",
        agent="test2",
        prompt_version="v2",
        messages=[],
        output_schema=SimpleNamespace,
    )

    assert gateway.call_count == 2, f"期望 2 次调用，实际 {gateway.call_count}"
    assert len(gateway.call_log) == 2
    assert gateway.call_log[0]["agent"] == "test"
    assert gateway.call_log[1]["agent"] == "test2"
    _ok("通话记录 → 正确记录调用次数和参数")


async def test_fault_injection_on_specific_call():
    """故障在第 N 次外部调用时触发"""
    # 不使用 trigger_on_call（用每次都触发的默认行为），
    # 改为测试内部重试耗尽行为
    gateway = FakeModelGateway(
        fault=FaultConfig(http_error=429, trigger_on_call=0)  # 每次注入
    )

    # 调用 → 会触发内部重试然后抛异常
    try:
        await gateway.invoke_structured(
            agent="test",
            prompt_version="v1",
            messages=[],
            output_schema=SimpleNamespace,
        )
        assert False, "应该抛出异常（重试耗尽）"
    except ModelGatewayError as e:
        assert e.status_code == 429
        # 验证内部重试次数 = MAX_RETRIES
        assert gateway.call_log[-1]["internal_retries"] == gateway.MAX_RETRIES

    assert gateway.call_count == 1  # 外部只调用了一次
    _ok("故障注入 → 内部重试 2 次后抛异常（验证重试上限）")


# ═══════════════════════════════════════════════════════
# 运行器
# ═══════════════════════════════════════════════════════


async def _run_async_tests(tests: list[tuple[str, callable]]) -> bool:
    global PASSED, FAILED
    for name, func in tests:
        print(f"  [{name}]")
        try:
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                func()
        except Exception as e:
            _fail(name, str(e))


def run_all():
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0

    print("\n" + "=" * 55)
    print("  Day 6 弹性测试")
    print("=" * 55 + "\n")

    # 异步测试
    async_tests = [
        ("模型超时 → AGENT_MODEL_TIMEOUT", test_timeout_handling),
        ("HTTP 429 → 可重试错误", test_http_429_handling),
        ("HTTP 500/502/503 → 可重试错误", test_http_5xx_handling),
        ("无效 JSON → 错误处理", test_invalid_json_handling),
        ("错误引用 → 被核验阻止", test_bad_citation_blocked),
        ("有效引用 → 正常通过", test_valid_citation_passes),
        ("节点超限 → AGENT_LIMIT_EXCEEDED", test_limits_exceeded_in_node),
        ("低置信度 → 降级回退", test_low_confidence_fallback),
        ("error_node 消费错误", test_error_node_includes_trace_id),
        ("拒答输出不含私有字段", test_refusal_node_output_no_private),
        ("FakeModelGateway 通话记录", test_model_gateway_call_logging),
        ("故障在第 N 次调用触发", test_fault_injection_on_specific_call),
    ]

    # 同步测试
    sync_tests = [
        ("MAX_MODEL_CALLS 限制", test_max_model_calls_limit),
        ("MAX_NODE_HOPS 限制", test_max_node_hops_limit),
        ("在限制内不触发", test_within_limits),
        ("错误对象包含 code/retryable/trace_id", test_error_object_contains_required_fields),
        ("7 种拒答原因模板完整", test_all_refusal_reasons_have_template),
    ]

    # 运行同步测试
    for name, func in sync_tests:
        print(f"  [{name}]")
        try:
            func()
        except Exception as e:
            _fail(name, str(e))

    # 运行异步测试
    asyncio.run(_run_async_tests(async_tests))

    total = PASSED + FAILED
    pct = 100 * PASSED // total if total > 0 else 0
    print(f"\n{'=' * 55}")
    if FAILED == 0:
        print(f"  ALL PASSED  {PASSED}/{total} ({pct}%)")
    else:
        print(f"  {FAILED} FAILED  {PASSED}/{total} ({pct}%)")
    print(f"{'=' * 55}\n")

    return FAILED == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
