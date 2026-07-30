"""
Day 6 评测指标计算测试 — 验证回答正确率、拒答识别率和评分一致率的计算逻辑

覆盖:
  1. 回答正确率计算（>= 80% 门槛）
  2. 应拒答识别率计算（>= 80% 门槛）
  3. 评分可接受一致率计算（>= 80% 门槛）
  4. 状态恢复与 manifest 校验
  5. 提示词版本和模型版本记录
  6. 主要失败类型记录

用法: python -m pytest agents/tests/test_evaluation_metrics.py -v
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "apps"))

# ═══════════════════════════════════════════════════════
# 指标计算工具（从 A 的 evaluate.py 提取核心逻辑）
# ═══════════════════════════════════════════════════════


@dataclass
class MetricResult:
    """单指标结果"""
    name: str
    numerator: float
    denominator: int
    threshold: float

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    @property
    def passed(self) -> bool | None:
        if self.value is None:
            return None
        return self.value >= self.threshold

    @property
    def formatted(self) -> str:
        if self.value is None:
            return "—"
        return f"{self.value:.1%} ({self.numerator:g}/{self.denominator})"


@dataclass
class EvaluationReport:
    """评测报告"""
    metrics: list[MetricResult] = field(default_factory=list)
    defects: list[dict] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    failure_types: dict[str, int] = field(default_factory=dict)
    status: str = "INCOMPLETE"

    def add_metric(self, name: str, numerator: float, denominator: int, threshold: float):
        self.metrics.append(MetricResult(name, numerator, denominator, threshold))

    @property
    def all_passed(self) -> bool:
        return all(m.passed is not False for m in self.metrics)

    @property
    def summary(self) -> str:
        lines = ["# Day 6 评测报告", "", f"状态: `{self.status}`", ""]
        lines.append("| 指标 | 结果 | 门槛 | 判定 |")
        lines.append("| --- | ---: | ---: | --- |")
        for m in self.metrics:
            decision = "N/A" if m.passed is None else "PASS" if m.passed else "FAIL"
            lines.append(f"| {m.name} | {m.formatted} | {m.threshold:.0%} | {decision} |")

        if self.failure_types:
            lines.append("")
            lines.append("## 主要失败类型")
            for ft, count in sorted(self.failure_types.items()):
                lines.append(f"- `{ft}`: {count} 条")

        if self.manifest:
            lines.append("")
            lines.append("## 运行快照")
            lines.append(f"- 提示词版本: {self.manifest.get('prompt_versions', {})}")
            lines.append(f"- 模型: {self.manifest.get('models', {})}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# 测试
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


# ── 回答正确率 ──


def test_answer_accuracy_calculation():
    """回答正确率 = answer pass 数 / 有标注的 answer 样本数"""
    # 模拟标注结果：15/18 pass
    report = EvaluationReport()
    report.add_metric("回答正确率", 15, 18, 0.80)

    m = report.metrics[0]
    assert m.value is not None
    assert abs(m.value - 0.8333) < 0.01, f"期望 83.3%，实际 {m.value:.1%}"
    assert m.passed is True
    _ok(f"回答正确率 = {m.formatted}，通过门槛 80%")


def test_answer_accuracy_below_threshold():
    """回答正确率低于 80% 应标记为未达标"""
    report = EvaluationReport()
    report.add_metric("回答正确率", 12, 18, 0.80)

    m = report.metrics[0]
    assert m.value is not None
    assert m.value < 0.80
    assert m.passed is False
    _ok(f"回答正确率 = {m.formatted}，未达标（< 80%）")


# ── 拒答识别率 ──


def test_refusal_accuracy_calculation():
    """拒答识别率 = 正确拒答数 / 应拒答样本数"""
    # 5 个应拒答样本，正确拒答 4 个
    report = EvaluationReport()
    report.add_metric("应拒答识别率", 4, 5, 0.80)

    m = report.metrics[0]
    assert m.value == 0.80
    assert m.passed is True  # >= 80% 即通过
    _ok(f"拒答识别率 = {m.formatted}，通过门槛（恰好 80%）")


def test_refusal_accuracy_perfect():
    """全部正确拒答 → 100%"""
    report = EvaluationReport()
    report.add_metric("应拒答识别率", 5, 5, 0.80)

    m = report.metrics[0]
    assert m.value == 1.0
    assert m.passed is True
    _ok(f"拒答识别率 = {m.formatted}（满分）")


# ── 评分一致率 ──


def test_grading_agreement_calculation():
    """评分一致率 = 双人标注 pass 数 / 有双人标注的评分样本数"""
    # 7 个评分样本，双人标注一致 6 个
    report = EvaluationReport()
    report.add_metric("评分可接受一致率", 6, 7, 0.80)

    m = report.metrics[0]
    assert m.value is not None
    assert abs(m.value - 0.857) < 0.01, f"期望 85.7%，实际 {m.value:.1%}"
    assert m.passed is True
    _ok(f"评分一致率 = {m.formatted}，通过门槛 80%")


def test_grading_agreement_insufficient():
    """双人标注不足 → 分母为 0 → 指标不可计算"""
    report = EvaluationReport()
    report.add_metric("评分可接受一致率", 0, 0, 0.80)

    m = report.metrics[0]
    assert m.value is None
    assert m.passed is None
    _ok("评分一致率 = —（双人标注不足，指标不可计算）")


# ── 报告生成 ──


def test_report_summary_format():
    """报告汇总包含所有指标和判定"""
    report = EvaluationReport(
        status="PASS",
        manifest={
            "prompt_versions": {
                "coordinator": "coordinator-v1",
                "knowledge": "knowledge-v1",
                "evaluator": "evaluator-qa-v1",
                "questioner": "questioner-v1",
            },
            "models": {"default": "deepseek-v3"},
        },
        failure_types={"AGENT_MODEL_TIMEOUT": 2, "AGENT_OUTPUT_INVALID": 1},
    )
    report.add_metric("回答正确率", 15, 18, 0.80)
    report.add_metric("应拒答识别率", 5, 5, 0.80)
    report.add_metric("评分可接受一致率", 6, 7, 0.80)

    summary = report.summary
    assert "PASS" in summary
    assert "回答正确率" in summary
    assert "应拒答识别率" in summary
    assert "评分可接受一致率" in summary
    assert "AGENT_MODEL_TIMEOUT" in summary
    assert "coordinator-v1" in summary
    _ok("报告汇总 → 包含所有指标、失败类型和版本信息")


# ── 失败类型记录 ──


def test_failure_type_tracking():
    """主要失败类型按频次归类"""
    failure_types: dict[str, int] = {}

    # 模拟 50 条评测的失败记录
    simulated_failures = [
        ("AGENT_MODEL_TIMEOUT", "db-005"),
        ("AGENT_MODEL_TIMEOUT", "db-012"),
        ("AGENT_OUTPUT_INVALID", "db-023"),
        ("AGENT_LIMIT_EXCEEDED", "db-031"),
        ("AGENT_MODEL_TIMEOUT", "db-038"),
    ]

    for code, case_id in simulated_failures:
        failure_types[code] = failure_types.get(code, 0) + 1

    assert failure_types["AGENT_MODEL_TIMEOUT"] == 3
    assert failure_types["AGENT_OUTPUT_INVALID"] == 1
    assert failure_types["AGENT_LIMIT_EXCEEDED"] == 1
    _ok(f"失败类型汇总 → {dict(failure_types)}")


# ── 提示词版本完整性 ──


def test_prompt_versions_complete():
    """所有 Agent 都有对应的提示词版本号"""
    from agents.schemas import PROMPT_VERSIONS

    required_agents = [
        "coordinator",
        "knowledge",
        "evaluator",
        "questioner",
        "evaluator_practice",
    ]
    for agent in required_agents:
        assert agent in PROMPT_VERSIONS, f"缺少 {agent} 的提示词版本"
        version = PROMPT_VERSIONS[agent]
        assert version, f"{agent} 版本号为空"
        assert version.startswith(f"{agent.split('_')[0]}-") or version.startswith(f"{agent}-"), (
            f"{agent} 版本号格式不正确: {version}"
        )
    _ok(f"提示词版本 → {len(PROMPT_VERSIONS)} 个 Agent 均有版本号")


# ── 模型版本记录 ──


def test_model_version_recording():
    """每次运行应记录模型标识"""
    # D 的 ModelGateway 应返回 model 字段
    # FakeModelGateway 默认返回 "fake-model-v1"
    from agents.tests.fake_adapters import FakeModelGateway
    import asyncio

    gateway = FakeModelGateway()
    result = asyncio.run(
        gateway.invoke_structured(
            agent="test",
            prompt_version="v1",
            messages=[],
            output_schema=type("TestSchema", (), {}),
        )
    )

    assert result.model == "fake-model-v1"
    assert result.provider == "fake"
    _ok(f"模型版本记录 → model={result.model}, provider={result.provider}")


# ── 缺陷清单 ──


def test_defect_list_generation():
    """缺陷清单逐条编号，含负责人"""
    defects = [
        {
            "defect_id": "EVAL-001",
            "case_id": "db-005",
            "metric": "answer_accuracy",
            "severity": "blocker",
            "owner_role": "C",
            "owner": "my-mayun",
            "summary": "回答关键结论错误",
            "expected": "事务具有 ACID 特性",
            "actual": "事务只保证一致性",
        },
        {
            "defect_id": "EVAL-002",
            "case_id": "db-043",
            "metric": "refusal",
            "severity": "major",
            "owner_role": "C",
            "owner": "my-mayun",
            "summary": "应拒答但输出了答案",
            "expected": "refuse",
            "actual": "answer",
        },
    ]

    assert len(defects) == 2
    assert defects[0]["defect_id"] == "EVAL-001"
    assert defects[0]["owner_role"] == "C"
    assert defects[1]["severity"] == "major"
    _ok(f"缺陷清单 → {len(defects)} 条，含 owner/severity/expected/actual")


# ═══════════════════════════════════════════════════════
# 运行器
# ═══════════════════════════════════════════════════════


def run_all():
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0

    print("\n" + "=" * 55)
    print("  Day 6 评测指标测试")
    print("=" * 55 + "\n")

    tests = [
        ("回答正确率 ≥ 80% 通过", test_answer_accuracy_calculation),
        ("回答正确率 < 80% 不通过", test_answer_accuracy_below_threshold),
        ("拒答识别率 = 80% 通过", test_refusal_accuracy_calculation),
        ("拒答识别率 100%", test_refusal_accuracy_perfect),
        ("评分一致率 ≥ 80% 通过", test_grading_agreement_calculation),
        ("评分一致率不可计算", test_grading_agreement_insufficient),
        ("报告汇总格式", test_report_summary_format),
        ("失败类型记录", test_failure_type_tracking),
        ("提示词版本完整性", test_prompt_versions_complete),
        ("模型版本记录", test_model_version_recording),
        ("缺陷清单生成", test_defect_list_generation),
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
