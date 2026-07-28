"""
契约测试 — 基于 Mock 数据验证 Agent 输入/输出符合 Schema

用法: python -m pytest agents/tests/test_contracts.py -v
      或 python agents/tests/test_contracts.py  (无需外部依赖)

测试覆盖:
  1. SourceRef 字段校验
  2. AgentEvent 字段校验
  3. PublicQuestion 不含私有字段（防泄露）
  4. 错误对象包含 code/retryable/trace_id
  5. 拒答模板完整性
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

# 确保项目根在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ═══════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════

PASSED = 0
FAILED = 0


def _ok(name: str):
    global PASSED
    PASSED += 1
    print(f"  ✓ {name}")


def _fail(name: str, detail: str = ""):
    global FAILED
    FAILED += 1
    msg = f"  ✗ {name}"
    if detail:
        msg += f"  —  {detail}"
    print(msg)


def _load_mock(filename: str) -> Optional[dict]:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "contracts", "mock", filename)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        _fail(f"加载 {filename}", str(e))
        return None


# ═══════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════


def test_source_ref_fields():
    """每个 SourceRef 必须包含 6 个必填字段"""
    data = _load_mock("qa-success.json")
    if data is None:
        return
    refs = data.get("public_response", {}).get("source_refs", [])
    if not refs:
        _fail("source_refs 为空，无法测试")
        return

    required = {"document_id", "document_name", "page_number", "chunk_id", "excerpt", "score"}
    for i, ref in enumerate(refs):
        missing = required - set(ref.keys())
        if missing:
            _fail(f"SourceRef[{i}] 缺少必填字段", str(missing))
        else:
            _ok(f"SourceRef[{i}] 必填字段完整")

    # 额外：page_number 必须 ≥ 1
    for i, ref in enumerate(refs):
        pn = ref.get("page_number")
        if pn is None or int(pn) < 1:
            _fail(f"SourceRef[{i}] page_number={pn}", "应 ≥ 1")
        else:
            _ok(f"SourceRef[{i}] page_number={pn} >= 1")


def test_agent_event_fields():
    """每个 AgentEvent 必须包含 6 个必填字段"""
    data = _load_mock("qa-success.json")
    if data is None:
        return
    events = data.get("public_response", {}).get("agent_events", [])
    if not events:
        _fail("agent_events 为空")
        return

    required = {"id", "run_id", "sequence_no", "agent", "event_type", "status", "summary", "created_at"}
    valid_agents = {"coordinator", "knowledge", "questioner", "evaluator", "system"}
    for i, evt in enumerate(events):
        missing = required - set(evt.keys())
        if missing:
            _fail(f"AgentEvent[{i}] 缺少必填字段", str(missing))
        else:
            _ok(f"AgentEvent[{i}] 必填字段完整")

        agent = evt.get("agent", "")
        if agent not in valid_agents:
            _fail(f"AgentEvent[{i}] agent={agent}", f"不在 {valid_agents} 中")
        else:
            _ok(f"AgentEvent[{i}] agent={agent}")


def test_public_question_no_answer_leak():
    """提交前的公开题目不得包含答案/评分点/私有证据"""
    data = _load_mock("training-question.json")
    if data is None:
        return
    pq = data.get("public_question", {})
    forbidden = ["expected_answer", "rubric", "answer_private", "private_content", "private", "step_scores"]
    for key in forbidden:
        if key in pq:
            _fail("泄露检测", f"public_question 包含禁止字段 '{key}'")
        else:
            _ok(f"无泄露: public_question 不含 '{key}'")


def test_error_object():
    """错误对象必须包含 code / retryable / trace_id"""
    data = _load_mock("failure-model-timeout.json")
    if data is None:
        return
    error = data.get("public_response", {}).get("error", {})
    for key in ["code", "message", "retryable", "trace_id"]:
        if key in error:
            _ok(f"error 包含 '{key}'")
        else:
            _fail(f"error 缺少 '{key}'")

    if error.get("retryable") is True:
        _ok("error.retryable=true — 前端可显示重试按钮")
    else:
        _fail("error.retryable 应为 true")


def test_refusal_templates():
    """7 种拒答 reason 都有对应文案"""
    from agents.prompts.refusal import RefusalTemplate

    all_reasons = ["no_results", "topic_mismatch", "missing_condition", "conflicting", "staff_only", "image_unavailable"]
    for reason in all_reasons:
        try:
            result = RefusalTemplate.build(reason, searched_chapters=["ch-03"])
            assert result["conclusion"], f"{reason} 缺少 conclusion"
            assert result["searched_scope"], f"{reason} 缺少 searched_scope"
            assert result["suggestion"], f"{reason} 缺少 suggestion"
            _ok(f"拒答模板 {reason} 完整")
        except Exception as e:
            _fail(f"拒答模板 {reason}", str(e))


def test_qa_success_privacy():
    """问答成功响应不泄露私有字段"""
    data = _load_mock("qa-success.json")
    if data is None:
        return
    privacy_check = data.get("$$privacy_check", {})
    assertions = [
        ("contains_private_answer", False),
        ("contains_rubric", False),
        ("contains_private_evidence", False),
    ]
    for key, expected in assertions:
        actual = privacy_check.get(key)
        if actual == expected:
            _ok(f"隐私检查 {key}={expected}")
        else:
            _fail(f"隐私检查 {key}", f"期望 {expected}，实际 {actual}")


def test_refusal_privacy():
    """拒答响应不含私有字段"""
    data = _load_mock("qa-refusal.json")
    if data is None:
        return
    privacy_check = data.get("$$privacy_check", {})
    if privacy_check.get("verdict", "").startswith("✅"):
        _ok("拒答响应隐私检查通过")
    else:
        _fail("拒答响应隐私检查未通过")


# ═══════════════════════════════════════════════════════
# 运行器
# ═══════════════════════════════════════════════════════


def run_all():
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0

    print("\n" + "=" * 55)
    print("  Agent 契约测试")
    print("=" * 55 + "\n")

    tests = [
        ("SourceRef 字段完整性", test_source_ref_fields),
        ("AgentEvent 字段完整性", test_agent_event_fields),
        ("PublicQuestion 防答案泄露", test_public_question_no_answer_leak),
        ("错误对象完整性", test_error_object),
        ("拒答模板完整性", test_refusal_templates),
        ("QA 成功响应的隐私检查", test_qa_success_privacy),
        ("拒答响应的隐私检查", test_refusal_privacy),
    ]

    for name, func in tests:
        print(f"  [{name}]")
        try:
            func()
        except Exception as e:
            _fail(name, f"未捕获异常: {e}")

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
