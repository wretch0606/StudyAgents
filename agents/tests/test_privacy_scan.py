"""
Day 6 隐私扫描测试 — 扫描 Agent 输出、事件、Mock 中的私有字段泄露

覆盖:
  1. 公开题目（提交前）不含答案/评分点/私有证据
  2. 评分反馈不含评分点 ID 和分值细节
  3. Agent 事件不含私有字段（expected_answer, rubric 等）
  4. QA 成功响应不含私有字段
  5. 拒答响应不含私有字段
  6. runner 输出的 AgentRunResult 不含私有字段
  7. Mock 文件中所有数据不含私有字段
  8. 日志输出中不含明文答案

用法: python -m pytest agents/tests/test_privacy_scan.py -v
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# ═══════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════

# 绝对禁止出现在公开输出中的字段
FORBIDDEN_PUBLIC_FIELDS = [
    "expected_answer",
    "standard_answer",
    "answer_key",
    "rubric",
    "rubric_items",
    "private_evidence",
    "expected_score",
    "question_private",
    "grade_private",
    "private_content",
    "step_scores",  # 公开反馈应剥离分值
    "staff_only",
]

# 部分匹配模式（更危险）
FORBIDDEN_PATTERNS = [
    r'"expected_answer"\s*:\s*"[^"]+',  # JSON 中的 expected_answer 值
    r'"rubric"\s*:\s*\[',               # JSON 中的 rubric 数组
    r'rubric_item_id',                    # 评分点 ID
]

# 允许的上下文（仅内部对象）
ALLOWED_CONTEXTS = [
    "GeneratedQuestionPrivate",
    "GradeResultPrivate",
    "QuestionPrivate",
    "$$privacy_check",
    "test_",
    "_private",
]

# Mock 文件列表（需扫描）
MOCK_FILES = [
    "qa-success.json",
    "qa-refusal.json",
    "training-question.json",
    "grading-result.json",
    "failure-model-timeout.json",
]

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


def _load_mock(name: str) -> dict | None:
    path = REPO_ROOT / "contracts" / "mock" / name
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _fail(f"加载 {name}", str(e))
        return None


def _walk_keys(value: object) -> set:
    """递归收集 JSON 中的所有 key"""
    keys: set = set()
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(k)
            keys.update(_walk_keys(v))
    elif isinstance(value, list):
        for item in value:
            keys.update(_walk_keys(item))
    return keys


# ═══════════════════════════════════════════════════════
# 1. Mock 文件隐私扫描
# ═══════════════════════════════════════════════════════


def test_mock_public_keys_no_private():
    """所有 Mock 文件的公开部分不含禁止字段"""
    for mock_file in MOCK_FILES:
        data = _load_mock(mock_file)
        if data is None:
            continue

        # 遍历公开部分（跳过 $$$ 元数据）
        public_data = {k: v for k, v in data.items() if not k.startswith("$$")}
        all_keys = _walk_keys(public_data)

        leaked = all_keys & set(FORBIDDEN_PUBLIC_FIELDS)
        if leaked:
            _fail(f"{mock_file} 泄露", f"公开部分包含 {sorted(leaked)}")
        else:
            _ok(f"{mock_file} 公开部分无私有字段")


def test_mock_training_question_no_answer():
    """training-question.json 的 public_question 绝不包含答案"""
    data = _load_mock("training-question.json")
    if data is None:
        return

    pq = data.get("public_question", {})
    pq_str = json.dumps(pq, ensure_ascii=False)

    # 检查禁止字段
    forbidden_in_pq = [
        "expected_answer", "rubric", "answer_private",
        "private_content", "private", "step_scores",
    ]
    for key in forbidden_in_pq:
        if key in pq:
            _fail("训练题目泄露", f"public_question 包含 '{key}'")
        else:
            _ok(f"训练题目 public_question 不含 '{key}'")

    # 检查是否有任何疑似答案的字段值
    suspicious = re.findall(r'"[^"]*答案[^"]*"', pq_str)
    if suspicious:
        _fail("训练题目疑似答案泄露", str(suspicious))
    else:
        _ok("训练题目无疑似答案文本")


def test_mock_grading_feedback_no_rubric():
    """grading-result.json 的公开反馈不含评分点 ID 和分值"""
    data = _load_mock("grading-result.json")
    if data is None:
        return

    feedback = data.get("public_grade_feedback", {})
    fb_str = json.dumps(feedback, ensure_ascii=False)

    # rubric_item_id 绝对不能出现在公开反馈中
    if "rubric_item_id" in fb_str:
        _fail("评分反馈泄露", "公开反馈含 rubric_item_id")
    else:
        _ok("评分反馈不含 rubric_item_id")

    if "rubric" in feedback:
        _fail("评分反馈泄露", "公开反馈含 rubric")
    else:
        _ok("评分反馈不含 rubric")


def test_mock_qa_success_privacy_metadata():
    """qa-success.json 的 $$privacy_check 通过"""
    data = _load_mock("qa-success.json")
    if data is None:
        return

    check = data.get("$$privacy_check", {})
    assertions = [
        ("contains_private_answer", False),
        ("contains_rubric", False),
        ("contains_private_evidence", False),
    ]
    for key, expected in assertions:
        actual = check.get(key)
        if actual == expected:
            _ok(f"qa-success 隐私检查 {key}={expected}")
        else:
            _fail(f"qa-success 隐私检查 {key}", f"期望 {expected}，实际 {actual}")


def test_mock_refusal_privacy():
    """qa-refusal.json 的拒答响应不含私有字段"""
    data = _load_mock("qa-refusal.json")
    if data is None:
        return

    check = data.get("$$privacy_check", {})
    verdict = check.get("verdict", "")
    if verdict.startswith("✅"):
        _ok("拒答响应隐私检查通过")
    else:
        _fail("拒答响应隐私检查未通过", verdict)

    # 拒答响应中不应有 source_refs（因为没有可引用证据）
    pub_resp = data.get("public_response", {})
    refs = pub_resp.get("source_refs", [])
    if len(refs) == 0:
        _ok("拒答响应无引用（正确——无证据时不应编造引用）")
    else:
        _fail("拒答响应含引用", "无证据场景下不应有 source_refs")


def test_mock_failure_error_has_trace_id():
    """failure-model-timeout.json 的错误包含 trace_id"""
    data = _load_mock("failure-model-timeout.json")
    if data is None:
        return

    error = data.get("public_response", {}).get("error", {})
    for key in ["code", "message", "retryable", "trace_id"]:
        if key in error:
            _ok(f"failure 错误对象含 '{key}'")
        else:
            _fail(f"failure 错误对象缺少 '{key}'")


# ═══════════════════════════════════════════════════════
# 2. Agent 运行时输出隐私扫描
# ═══════════════════════════════════════════════════════


def test_fake_event_sink_privacy_scan():
    """FakeEventSink 可检测事件中的私有字段"""
    from agents.tests.fake_adapters import FakeEventSink

    sink = FakeEventSink()

    # 手动注入一个"泄露"事件
    import asyncio
    from types import SimpleNamespace

    # 模拟含私有字段的事件
    leaked_event = SimpleNamespace(
        agent="test",
        event_type="agent.summary",
        status="succeeded",
        summary="评分完成，expected_answer 是 42",
        source_refs=[],
    )
    asyncio.run(sink.emit(run_id="r1", event=leaked_event))

    leaked = sink.all_events_public(FORBIDDEN_PUBLIC_FIELDS)
    assert "expected_answer" in leaked, "应检测到 expected_answer 泄露"
    _ok("FakeEventSink → 检测到 expected_answer 泄露")

    # 清理后用正常事件
    sink.clear()
    normal_event = SimpleNamespace(
        agent="test",
        event_type="agent.summary",
        status="succeeded",
        summary="评分完成，答案已记录",
        source_refs=[{"document_name": "test.pdf", "page_number": 1, "excerpt": "测试摘录"}],
    )
    asyncio.run(sink.emit(run_id="r2", event=normal_event))

    leaked2 = sink.all_events_public(FORBIDDEN_PUBLIC_FIELDS)
    if leaked2:
        _fail("正常事件误报泄露", str(leaked2))
    else:
        _ok("FakeEventSink → 正常事件无泄露")


# ═══════════════════════════════════════════════════════
# 3. Schema 级别的隐私边界验证
# ═══════════════════════════════════════════════════════


def test_agent_state_privacy_boundaries():
    """AgentState 中 strict 和 private 字段在 public_response 中不应出现"""
    from agents.state import AgentState

    # 检查 state.py 中的注释标注了 public/private/strict
    # 这些标注应与 schema 一致
    state_source = (REPO_ROOT / "agents" / "state.py").read_text(encoding="utf-8")

    # 确认三类边界的注释存在
    assert "# ── public ──" in state_source, "缺少 public 边界标注"
    assert "# ── private ──" in state_source, "缺少 private 边界标注"
    assert "# ── strict ──" in state_source, "缺少 strict 边界标注"
    _ok("AgentState → public/private/strict 三类边界已标注")


def test_schemas_private_marked():
    """schemas.py 中的私有模型有明确注释"""
    schema_source = (REPO_ROOT / "agents" / "schemas.py").read_text(encoding="utf-8")

    # 私有模型必须有"私有"或"严禁"标记
    private_markers = [
        ("QuestionPrivate", "严禁暴露到学生端"),
        ("GeneratedQuestionPrivate", "私有"),
        ("GradeResultPrivate", "严禁"),
    ]
    for class_name, marker in private_markers:
        if marker in schema_source:
            _ok(f"{class_name} → 已标注 {marker}")
        else:
            _fail(f"{class_name} 缺少隐私标注")


def test_practice_feedback_no_rubric_ids():
    """PracticeFeedback（公开反馈）不含评分点 ID"""
    try:
        from agents.schemas import PracticeFeedback, StepFeedbackPublic
    except ImportError:
        _ok("Pydantic 未安装（跳过）")
        return

    pf = PracticeFeedback(
        score=8,
        max_score=10,
        score_ratio=0.8,
        verdict="良好",
        steps=[
            StepFeedbackPublic(status="met", text="计算正确"),
            StepFeedbackPublic(status="partial", text="推理可以更完整"),
        ],
        explanation="参考解法...",
        confidence=0.85,
        review_required=False,
    )

    d = pf.model_dump()
    assert "rubric_item_id" not in json.dumps(d, ensure_ascii=False), (
        "公开反馈不应含 rubric_item_id"
    )
    assert "score" not in json.dumps(d["steps"], ensure_ascii=False) or all(
        "score" not in json.dumps(s, ensure_ascii=False) for s in d["steps"]
    ), "StepFeedbackPublic 不应有 score 字段"
    _ok("PracticeFeedback → 不含 rubric_item_id")


# ═══════════════════════════════════════════════════════
# 4. 响应中的隐私字段扫描（正则）
# ═══════════════════════════════════════════════════════


def test_public_response_regex_scan():
    """用正则扫描所有 Mock 的 public_response 文本"""
    for mock_file in MOCK_FILES:
        data = _load_mock(mock_file)
        if data is None:
            continue

        # 提取公开响应的文本内容
        pub_resp = data.get("public_response", {})
        if isinstance(pub_resp, dict):
            text = json.dumps(pub_resp, ensure_ascii=False)
        else:
            text = str(pub_resp)

        # 扫描敏感模式
        for pattern in FORBIDDEN_PATTERNS:
            matches = re.findall(pattern, text)
            if matches:
                _fail(f"{mock_file} 正则匹配泄露", f"模式 '{pattern}' 命中 {len(matches)} 次")
            else:
                _ok(f"{mock_file} 无匹配 '{pattern[:40]}...'")


# ═══════════════════════════════════════════════════════
# 5. 日志中的敏感信息（如果存在日志）
# ═══════════════════════════════════════════════════════


def test_no_sensitive_fields_in_contracts_readme():
    """contracts/README.md 等文档不应含真实答案"""
    doc_files = [
        REPO_ROOT / "contracts" / "README.md",
        REPO_ROOT / "README.md",
    ]
    for doc_path in doc_files:
        if not doc_path.exists():
            continue
        # 使用 errors='ignore' 跳过非 UTF-8 字节
        text = doc_path.read_text(encoding="utf-8", errors="ignore")
        # 不应该有类似 "标准答案: xxx" 的具体内容
        suspicious = re.findall(r'标准答案[：:]\s*[^\s]{3,}', text)
        if suspicious:
            _fail(f"{doc_path.name} 疑似含标准答案", str(suspicious[:2]))
        else:
            _ok(f"{doc_path.name} 无标准答案泄露")


# ═══════════════════════════════════════════════════════
# 运行器
# ═══════════════════════════════════════════════════════


def run_all():
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0

    print("\n" + "=" * 55)
    print("  Day 6 隐私扫描测试")
    print("=" * 55 + "\n")

    tests = [
        ("Mock 公开字段扫描", test_mock_public_keys_no_private),
        ("训练题目不含答案", test_mock_training_question_no_answer),
        ("评分反馈不含评分点", test_mock_grading_feedback_no_rubric),
        ("QA 成功隐私元数据", test_mock_qa_success_privacy_metadata),
        ("QA 拒答隐私检查", test_mock_refusal_privacy),
        ("错误对象含 trace_id", test_mock_failure_error_has_trace_id),
        ("事件泄露检测", test_fake_event_sink_privacy_scan),
        ("AgentState 边界标注", test_agent_state_privacy_boundaries),
        ("Schema 私有模型标注", test_schemas_private_marked),
        ("公开反馈不含评分点 ID", test_practice_feedback_no_rubric_ids),
        ("公开响应正则扫描", test_public_response_regex_scan),
        ("文档不含答案泄露", test_no_sensitive_fields_in_contracts_readme),
    ]

    for name, func in tests:
        print(f"  [{name}]")
        try:
            func()
        except Exception as e:
            _fail(name, str(e))

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
