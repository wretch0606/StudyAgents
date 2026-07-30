"""Validate the 50-case baseline and produce conservative evaluation reports.

Only the Python standard library is used so the evaluator can run before the
full application dependency stack is available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = ROOT / "cases.public.jsonl"
DEFAULT_POLICIES = ROOT / "policies.json"

EXPECTED_DISTRIBUTION = {
    "fact_qa": 15,
    "computation_short_answer": 15,
    "visual": 10,
    "refusal": 5,
    "cross_knowledge": 5,
}
REQUIRED_TAGS = {
    "in_scope",
    "out_of_scope",
    "multi_page",
    "ambiguous",
    "conflict",
    "visual",
    "prompt_injection",
}
SOURCE_PAGE_LIMITS = {
    "db-intro-digital": 15,
    "db-exam-scan": 2,
}
REQUIRED_CASE_KEYS = {
    "case_id",
    "category",
    "mode",
    "query",
    "student_answer",
    "source_scope",
    "expected_behavior",
    "expected_evidence",
    "evidence_match",
    "scoring_policy",
    "critical",
    "tags",
}
FORBIDDEN_PUBLIC_KEYS = {
    "expected_answer",
    "standard_answer",
    "answer_key",
    "rubric",
    "rubric_items",
    "private_evidence",
    "expected_score",
}
JUDGMENTS = {"pass", "fail", "na"}
REQUIRED_MANIFEST_KEYS = {
    "run_id",
    "created_at",
    "code_commit",
    "material_commit",
    "material_manifest_sha256",
    "dataset_sha256",
    "policy_sha256",
    "models",
    "prompt_versions",
    "retrieval_parameters",
    "environment",
}


@dataclass(frozen=True)
class Metric:
    numerator: float
    denominator: int

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level JSON value must be an object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: each line must be an object")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def validate_cases(
    cases: list[dict[str, Any]],
    policy_document: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    policies = policy_document.get("policies", {})

    if len(cases) != 50:
        errors.append(f"expected exactly 50 cases, found {len(cases)}")

    ids = [case.get("case_id") for case in cases]
    duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate case IDs: {', '.join(str(value) for value in duplicates)}")

    distribution = Counter(case.get("category") for case in cases)
    if dict(distribution) != EXPECTED_DISTRIBUTION:
        errors.append(
            "category distribution mismatch: "
            f"expected {EXPECTED_DISTRIBUTION}, found {dict(distribution)}"
        )

    all_tags: set[str] = set()
    for index, case in enumerate(cases, 1):
        case_id = case.get("case_id", f"line-{index}")
        missing = REQUIRED_CASE_KEYS - set(case)
        extra = set(case) - REQUIRED_CASE_KEYS
        if missing:
            errors.append(f"{case_id}: missing keys {sorted(missing)}")
        if extra:
            errors.append(f"{case_id}: unexpected keys {sorted(extra)}")

        if not isinstance(case_id, str) or not re.fullmatch(r"db-\d{3}", case_id):
            errors.append(f"{case_id}: invalid case_id")

        query = case.get("query")
        if not isinstance(query, str) or not 4 <= len(query) <= 300:
            errors.append(f"{case_id}: query must contain 4-300 characters")
        if isinstance(query, str) and re.search(r"[A-Za-z]:[\\/]", query):
            errors.append(f"{case_id}: query contains a local absolute path")

        tags = case.get("tags")
        if not isinstance(tags, list) or not tags or len(tags) != len(set(tags)):
            errors.append(f"{case_id}: tags must be a non-empty unique list")
        else:
            all_tags.update(str(tag) for tag in tags)

        source_scope = case.get("source_scope")
        if not isinstance(source_scope, list) or len(source_scope) != len(set(source_scope)):
            errors.append(f"{case_id}: source_scope must be a unique list")
        elif unknown_sources := set(source_scope) - set(SOURCE_PAGE_LIMITS):
            errors.append(f"{case_id}: unknown source IDs {sorted(unknown_sources)}")

        evidence = case.get("expected_evidence")
        match = case.get("evidence_match")
        if not isinstance(evidence, list):
            errors.append(f"{case_id}: expected_evidence must be a list")
            evidence = []
        if match == "none" and evidence:
            errors.append(f"{case_id}: evidence_match=none requires no evidence")
        if match in {"any", "all"} and not evidence:
            errors.append(f"{case_id}: evidence_match={match} requires evidence")
        if match not in {"any", "all", "none"}:
            errors.append(f"{case_id}: invalid evidence_match {match!r}")

        scoped_ids = set(source_scope or [])
        for ref in evidence:
            if not isinstance(ref, dict):
                errors.append(f"{case_id}: evidence entries must be objects")
                continue
            if set(ref) != {"document_id", "pages"}:
                errors.append(f"{case_id}: evidence entry must contain document_id and pages")
            if ref.get("document_id") not in scoped_ids:
                errors.append(f"{case_id}: evidence document is outside source_scope")
            pages = ref.get("pages")
            if (
                not isinstance(pages, list)
                or not pages
                or len(pages) != len(set(pages))
                or any(not isinstance(page, int) or page < 1 for page in pages)
            ):
                errors.append(f"{case_id}: evidence pages must be unique positive integers")
            elif ref.get("document_id") in SOURCE_PAGE_LIMITS:
                max_page = SOURCE_PAGE_LIMITS[ref["document_id"]]
                if any(page > max_page for page in pages):
                    errors.append(
                        f"{case_id}: evidence page exceeds {ref['document_id']} "
                        f"limit of {max_page}"
                    )

        behavior = case.get("expected_behavior")
        policy_id = case.get("scoring_policy")
        policy = policies.get(policy_id)
        if not policy:
            errors.append(f"{case_id}: unknown scoring policy {policy_id!r}")
        elif behavior not in policy.get("applies_to", []):
            errors.append(f"{case_id}: policy {policy_id} does not apply to {behavior}")

        if case.get("mode") == "training":
            if behavior != "grade" or not isinstance(case.get("student_answer"), str):
                errors.append(
                    f"{case_id}: training cases require a synthetic answer "
                    "and grade behavior"
                )
        elif case.get("student_answer") is not None:
            errors.append(f"{case_id}: qa cases must use null student_answer")

        forbidden = FORBIDDEN_PUBLIC_KEYS.intersection(_walk_keys(case))
        if forbidden:
            errors.append(f"{case_id}: public case contains private keys {sorted(forbidden)}")

    missing_tags = REQUIRED_TAGS - all_tags
    if missing_tags:
        errors.append(f"required scenario tags missing: {sorted(missing_tags)}")

    critical_count = sum(case.get("critical") is True for case in cases)
    if critical_count < 20:
        errors.append(f"at least 20 critical cases are required, found {critical_count}")

    return errors


def _expected_refs(case: dict[str, Any]) -> set[tuple[str, int]]:
    refs: set[tuple[str, int]] = set()
    for evidence in case["expected_evidence"]:
        for page in evidence["pages"]:
            refs.add((evidence["document_id"], page))
    return refs


def _retrieved_refs(result: dict[str, Any], limit: int = 5) -> list[tuple[str, int]]:
    refs: list[tuple[str, int]] = []
    for evidence in result.get("retrieved_evidence", [])[:limit]:
        document_id = evidence.get("document_id")
        page = evidence.get("page")
        if isinstance(document_id, str) and isinstance(page, int):
            refs.append((document_id, page))
    return refs


def _recall_metric(
    cases: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, Any]],
) -> Metric:
    recall_sum = 0.0
    denominator = 0
    for case in cases:
        expected = _expected_refs(case)
        result = results_by_id.get(case["case_id"])
        if not expected or result is None:
            continue
        retrieved = set(_retrieved_refs(result))
        recall_sum += len(expected.intersection(retrieved)) / len(expected)
        denominator += 1
    return Metric(recall_sum, denominator)


def _behavior_metric(
    cases: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, Any]],
    expected_behavior: str,
) -> Metric:
    relevant = [case for case in cases if case["expected_behavior"] == expected_behavior]
    completed = [case for case in relevant if case["case_id"] in results_by_id]
    passed = sum(
        results_by_id[case["case_id"]].get("actual_behavior") == expected_behavior
        for case in completed
    )
    return Metric(float(passed), len(completed))


def _annotation_metric(
    cases: list[dict[str, Any]],
    annotations_by_id: dict[str, list[dict[str, Any]]],
    metric_name: str,
    policies: dict[str, Any],
    results_by_id: dict[str, dict[str, Any]],
    arbitrations_by_key: dict[tuple[str, str], dict[str, Any]],
) -> tuple[Metric, list[str], list[str], list[str], int]:
    numerator = 0.0
    denominator = 0
    incomplete: list[str] = []
    disagreements: list[str] = []
    failed: list[str] = []
    resolved = 0

    for case in cases:
        dimensions = policies[case["scoring_policy"]]["dimensions"]
        if metric_name not in dimensions:
            continue

        result = results_by_id.get(case["case_id"])
        if result and result.get("actual_behavior") != case["expected_behavior"]:
            denominator += 1
            failed.append(case["case_id"])
            continue

        distinct: dict[str, str] = {}
        for annotation in annotations_by_id.get(case["case_id"], []):
            annotator_id = annotation.get("annotator_id")
            judgment = annotation.get("judgments", {}).get(metric_name)
            if isinstance(annotator_id, str) and judgment in {"pass", "fail"}:
                distinct[annotator_id] = judgment

        required = 2 if case["critical"] else 1
        if len(distinct) < required:
            incomplete.append(case["case_id"])
            continue

        selected = list(distinct.values())
        denominator += 1
        if len(set(selected)) > 1:
            arbitration = arbitrations_by_key.get((case["case_id"], metric_name))
            if arbitration is None:
                disagreements.append(case["case_id"])
                continue
            resolved += 1
            if arbitration["judgment"] == "pass":
                numerator += 1
            else:
                failed.append(case["case_id"])
            continue
        if selected[0] == "pass":
            numerator += 1
        else:
            failed.append(case["case_id"])

    return Metric(numerator, denominator), incomplete, disagreements, failed, resolved


def validate_results(
    results: list[dict[str, Any]],
    valid_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for row in results:
        case_id = row.get("case_id")
        if case_id not in valid_ids:
            errors.append(f"result has unknown case_id {case_id!r}")
        if case_id in seen:
            errors.append(f"duplicate result for {case_id}")
        seen.add(case_id)
        if row.get("actual_behavior") not in {
            "answer",
            "refuse",
            "clarify",
            "flag_conflict",
            "grade",
            "error",
        }:
            errors.append(f"{case_id}: invalid actual_behavior")
        if not isinstance(row.get("retrieved_evidence", []), list):
            errors.append(f"{case_id}: retrieved_evidence must be a list")
    return errors


def validate_annotations(
    annotations: list[dict[str, Any]],
    valid_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in annotations:
        case_id = row.get("case_id")
        annotator_id = row.get("annotator_id")
        if case_id not in valid_ids:
            errors.append(f"annotation has unknown case_id {case_id!r}")
        if not isinstance(annotator_id, str) or not annotator_id.strip():
            errors.append(f"{case_id}: annotator_id is required")
            continue
        key = (str(case_id), annotator_id)
        if key in seen:
            errors.append(f"duplicate annotation from {annotator_id} for {case_id}")
        seen.add(key)
        judgments = row.get("judgments")
        if not isinstance(judgments, dict):
            errors.append(f"{case_id}/{annotator_id}: judgments must be an object")
            continue
        expected_judgment_keys = {"answer", "citation", "refusal", "grading"}
        if set(judgments) != expected_judgment_keys:
            errors.append(
                f"{case_id}/{annotator_id}: judgments must contain "
                f"{sorted(expected_judgment_keys)}"
            )
        invalid = {value for value in judgments.values() if value not in JUDGMENTS}
        if invalid:
            errors.append(f"{case_id}/{annotator_id}: invalid judgments {sorted(invalid)}")
    return errors


def validate_arbitrations(
    arbitrations: list[dict[str, Any]],
    valid_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in arbitrations:
        case_id = row.get("case_id")
        metric = row.get("metric")
        arbiter_id = row.get("arbiter_id")
        judgment = row.get("judgment")
        reason = row.get("reason")
        if case_id not in valid_ids:
            errors.append(f"arbitration has unknown case_id {case_id!r}")
        if metric not in {"answer", "citation", "grading"}:
            errors.append(f"{case_id}: invalid arbitration metric {metric!r}")
        key = (str(case_id), str(metric))
        if key in seen:
            errors.append(f"duplicate arbitration for {case_id}/{metric}")
        seen.add(key)
        if not isinstance(arbiter_id, str) or not arbiter_id.strip():
            errors.append(f"{case_id}/{metric}: arbiter_id is required")
        if judgment not in {"pass", "fail"}:
            errors.append(f"{case_id}/{metric}: judgment must be pass or fail")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{case_id}/{metric}: reason is required")
    return errors


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_MANIFEST_KEYS - set(manifest)
    if missing:
        errors.append(f"run manifest is missing keys {sorted(missing)}")
    for key in ("run_id", "created_at", "code_commit", "material_commit"):
        if key in manifest and (
            not isinstance(manifest[key], str) or not manifest[key].strip()
        ):
            errors.append(f"run manifest field {key} must be a non-empty string")
    for key in ("models", "prompt_versions", "retrieval_parameters", "environment"):
        if key in manifest and not isinstance(manifest[key], dict):
            errors.append(f"run manifest field {key} must be an object")
    return errors


def _format_metric(metric: Metric) -> str:
    if metric.value is None:
        return "—"
    return f"{metric.value:.1%} ({metric.numerator:g}/{metric.denominator})"


def _metric_pass(metric: Metric, threshold: float) -> bool | None:
    if metric.value is None:
        return None
    return metric.value >= threshold


def _make_defect(
    number: int,
    case_id: str,
    metric: str,
    owner_role: str,
    owner: str,
    summary: str,
    expected: str,
    actual: str,
) -> dict[str, Any]:
    return {
        "defect_id": f"EVAL-{number:03d}",
        "case_id": case_id,
        "metric": metric,
        "severity": "blocker" if metric in {"missing_result", "annotation"} else "major",
        "owner_role": owner_role,
        "owner": owner,
        "summary": summary,
        "reproduction_steps": [
            f"从固定运行快照重新执行 {case_id}",
            "保存原始检索、最终响应、Agent 事件和 trace_id",
            "用同一评测脚本重新生成报告并比较结果",
        ],
        "expected": expected,
        "actual": actual,
    }


def build_report(
    cases: list[dict[str, Any]],
    policy_document: dict[str, Any],
    results: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    manifest: dict[str, Any],
    arbitrations: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    policies = policy_document["policies"]
    gates = policy_document["quality_gates"]
    results_by_id = {row["case_id"]: row for row in results}
    annotations_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in annotations:
        annotations_by_id[row["case_id"]].append(row)
    arbitrations_by_key = {
        (row["case_id"], row["metric"]): row for row in (arbitrations or [])
    }

    recall = _recall_metric(cases, results_by_id)
    answer, answer_missing, answer_disagreements, answer_failed, answer_resolved = (
        _annotation_metric(
            cases,
            annotations_by_id,
            "answer",
            policies,
            results_by_id,
            arbitrations_by_key,
        )
    )
    citation, citation_missing, citation_disagreements, citation_failed, citation_resolved = (
        _annotation_metric(
            cases,
            annotations_by_id,
            "citation",
            policies,
            results_by_id,
            arbitrations_by_key,
        )
    )
    refusal = _behavior_metric(cases, results_by_id, "refuse")
    grading, grading_missing, grading_disagreements, grading_failed, grading_resolved = (
        _annotation_metric(
            cases,
            annotations_by_id,
            "grading",
            policies,
            results_by_id,
            arbitrations_by_key,
        )
    )
    resolved_arbitrations = answer_resolved + citation_resolved + grading_resolved
    metrics = {
        "recall_at_5": recall,
        "answer_accuracy": answer,
        "citation_accuracy": citation,
        "refusal_accuracy": refusal,
        "grading_agreement": grading,
    }

    missing_results = [case["case_id"] for case in cases if case["case_id"] not in results_by_id]
    critical_annotation_missing = [
        case["case_id"]
        for case in cases
        if case["critical"]
        and len(
            {
                row.get("annotator_id")
                for row in annotations_by_id.get(case["case_id"], [])
                if isinstance(row.get("annotator_id"), str)
            }
        )
        < 2
    ]
    missing_annotations = sorted(
        set(
            answer_missing
            + citation_missing
            + grading_missing
            + critical_annotation_missing
        )
    )
    disagreements = sorted(
        set(answer_disagreements + citation_disagreements + grading_disagreements)
    )
    complete = not missing_results and not missing_annotations and not disagreements
    gate_states = {
        name: _metric_pass(metric, gates[name]) for name, metric in metrics.items()
    }
    status = (
        "INCOMPLETE"
        if not complete
        else "PASS"
        if all(gate_states.values())
        else "FAIL"
    )

    defects: list[dict[str, Any]] = []
    defect_no = 1
    for case_id in missing_results:
        defects.append(
            _make_defect(
                defect_no,
                case_id,
                "missing_result",
                "D",
                "后端负责人（待加入）",
                "缺少系统运行结果",
                "导出检索、行为、耗时和 trace_id",
                "结果文件中没有该样本",
            )
        )
        defect_no += 1
    for case_id in missing_annotations:
        defects.append(
            _make_defect(
                defect_no,
                case_id,
                "annotation",
                "A",
                "wretch0606",
                "关键指标缺少规定人数的独立标注",
                "关键样本至少两名不同标注者，其他样本至少一名",
                "有效标注数量不足",
            )
        )
        defect_no += 1
    for case_id in disagreements:
        defects.append(
            _make_defect(
                defect_no,
                case_id,
                "annotation",
                "A",
                "wretch0606",
                "人工标注存在分歧",
                "记录仲裁结论及理由",
                "首轮标注者给出相反判断",
            )
        )
        defect_no += 1

    metric_failures = (
        ("answer_accuracy", answer_failed, "C", "my-mayun"),
        ("citation_accuracy", citation_failed, "B", "ssf13546"),
        ("grading_agreement", grading_failed, "C", "my-mayun"),
    )
    for metric, case_ids, owner_role, owner in metric_failures:
        for case_id in sorted(set(case_ids)):
            defects.append(
                _make_defect(
                    defect_no,
                    case_id,
                    metric,
                    owner_role,
                    owner,
                    f"{metric} judgment failed",
                    "pass under the fixed scoring policy",
                    "fail after annotation or deterministic behavior check",
                )
            )
            defect_no += 1

    for case in cases:
        result = results_by_id.get(case["case_id"])
        if result is None:
            continue
        expected_refs = _expected_refs(case)
        actual_refs = set(_retrieved_refs(result))
        if expected_refs and not expected_refs.intersection(actual_refs):
            defects.append(
                _make_defect(
                    defect_no,
                    case["case_id"],
                    "recall_at_5",
                    "B",
                    "ssf13546",
                    "Top 5 未命中任何期望证据页",
                    f"命中 {sorted(expected_refs)}",
                    f"Top 5 为 {sorted(actual_refs)}",
                )
            )
            defect_no += 1
        if result.get("actual_behavior") != case["expected_behavior"]:
            defects.append(
                _make_defect(
                    defect_no,
                    case["case_id"],
                    "behavior",
                    "C",
                    "my-mayun",
                    "最终行为与期望不一致",
                    case["expected_behavior"],
                    str(result.get("actual_behavior")),
                )
            )
            defect_no += 1

    elapsed = [
        float(row["latency_ms"])
        for row in results
        if isinstance(row.get("latency_ms"), int | float)
    ]
    p95 = None
    if elapsed:
        ordered = sorted(elapsed)
        p95 = ordered[max(0, int(len(ordered) * 0.95 + 0.999999) - 1)]

    category_rows: list[str] = []
    for category in EXPECTED_DISTRIBUTION:
        subset = [case for case in cases if case["category"] == category]
        category_recall = _recall_metric(subset, results_by_id)
        behavior_hits = sum(
            results_by_id[case["case_id"]].get("actual_behavior") == case["expected_behavior"]
            for case in subset
            if case["case_id"] in results_by_id
        )
        behavior_total = sum(case["case_id"] in results_by_id for case in subset)
        behavior_metric = Metric(float(behavior_hits), behavior_total)
        category_rows.append(
            f"| `{category}` | {_format_metric(category_recall)} | "
            f"{_format_metric(behavior_metric)} |"
        )

    lines = [
        "# StudyAgents 50 条评测报告",
        "",
        f"> 状态：`{status}`｜数据集版本：`{policy_document.get('dataset_version', 'unknown')}`",
        "",
        "## 运行快照",
        "",
        f"- Run ID：`{manifest.get('run_id', 'missing')}`",
        f"- 代码提交：`{manifest.get('code_commit', 'missing')}`",
        f"- 资料提交：`{manifest.get('material_commit', 'missing')}`",
        f"- 数据集 SHA-256：`{manifest.get('dataset_sha256', 'missing')}`",
        f"- 策略 SHA-256：`{manifest.get('policy_sha256', 'missing')}`",
        f"- 模型：`{manifest.get('models', {})}`",
        f"- 提示词版本：`{manifest.get('prompt_versions', {})}`",
        f"- 检索参数：`{manifest.get('retrieval_parameters', {})}`",
        "",
        "## 总体指标",
        "",
        "| 指标 | 结果 | 门槛 | 判定 |",
        "| --- | ---: | ---: | --- |",
    ]
    labels = {
        "recall_at_5": "Recall@5",
        "answer_accuracy": "回答正确率",
        "citation_accuracy": "引用准确率",
        "refusal_accuracy": "拒答识别率",
        "grading_agreement": "评分可接受一致率",
    }
    for name, metric in metrics.items():
        gate_state = gate_states[name]
        decision = "未完成" if gate_state is None else "通过" if gate_state else "未达标"
        lines.append(
            f"| {labels[name]} | {_format_metric(metric)} | {gates[name]:.0%} | {decision} |"
        )
    lines.extend(
        [
            f"| 最终响应 P95 | {'—' if p95 is None else f'{p95:.0f} ms'} | 30 s | "
            f"{'未完成' if p95 is None else '通过' if p95 <= 30000 else '未达标'} |",
            "",
            "## 分组指标",
            "",
            "| 类别 | Recall@5 | 行为符合率 |",
            "| --- | ---: | ---: |",
            *category_rows,
            "",
            "## 完整性与分歧",
            "",
            f"- 缺少运行结果：{len(missing_results)} 条。",
            f"- 缺少规定人数标注：{len(missing_annotations)} 条。",
            f"- 未仲裁标注分歧：{len(disagreements)} 条。",
            f"- 已仲裁标注分歧：{resolved_arbitrations} 条。",
            f"- 已生成缺陷：{len(defects)} 条。",
            "",
            "## 主要失败类型",
            "",
        ]
    )
    defect_counts = Counter(defect["metric"] for defect in defects)
    if defect_counts:
        for metric, count in sorted(defect_counts.items()):
            lines.append(f"- `{metric}`：{count} 条。")
    else:
        lines.append("- 未发现失败。")
    lines.extend(
        [
            "",
            "## 结论",
            "",
            (
                "所有必需结果和双人标注已齐备，且质量门槛均通过。"
                if status == "PASS"
                else "输入齐备，但至少一项质量门槛未达标；按缺陷清单冻结新功能并修复。"
                if status == "FAIL"
                else "当前报告不完整，不得用于宣称答辩版本达标。"
                "先补齐运行结果、双人标注和分歧仲裁。"
            ),
            "",
        ]
    )
    return "\n".join(lines), defects


def _validate_command(args: argparse.Namespace) -> int:
    cases = load_jsonl(args.cases)
    policies = load_json(args.policies)
    errors = validate_cases(cases, policies)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(cases)} cases; distribution={dict(Counter(c['category'] for c in cases))}; "
        f"critical={sum(c['critical'] for c in cases)}"
    )
    return 0


def _report_command(args: argparse.Namespace) -> int:
    cases = load_jsonl(args.cases)
    policies = load_json(args.policies)
    results = load_jsonl(args.results)
    annotations = load_jsonl(args.annotations)
    arbitrations = load_jsonl(args.arbitrations) if args.arbitrations else []
    manifest = load_json(args.manifest)

    errors = validate_cases(cases, policies)
    valid_ids = {case["case_id"] for case in cases}
    errors.extend(validate_results(results, valid_ids))
    errors.extend(validate_annotations(annotations, valid_ids))
    errors.extend(validate_arbitrations(arbitrations, valid_ids))
    errors.extend(validate_manifest(manifest))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    report, defects = build_report(
        cases,
        policies,
        results,
        annotations,
        manifest,
        arbitrations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8", newline="\n")
    write_jsonl(args.defects, defects)
    print(f"Wrote {args.output} and {len(defects)} defects to {args.defects}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(func=None)
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="validate the public 50-case set")
    validate_parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    validate_parser.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    validate_parser.set_defaults(func=_validate_command)

    report_parser = subparsers.add_parser("report", help="calculate metrics and defects")
    report_parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    report_parser.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    report_parser.add_argument("--results", type=Path, required=True)
    report_parser.add_argument("--annotations", type=Path, required=True)
    report_parser.add_argument("--arbitrations", type=Path)
    report_parser.add_argument("--manifest", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    report_parser.add_argument("--defects", type=Path, required=True)
    report_parser.set_defaults(func=_report_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
