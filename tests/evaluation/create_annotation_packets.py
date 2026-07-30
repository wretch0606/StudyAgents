"""Create private, reviewer-specific annotation packets for Issue #18."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVALUATION_DIR = ROOT / "tests" / "evaluation"
DEFAULT_CASES = EVALUATION_DIR / "cases.public.jsonl"
DEFAULT_ARTIFACTS = EVALUATION_DIR / "private" / "run-artifacts.jsonl"
DEFAULT_OUTPUT_DIR = EVALUATION_DIR / "private" / "annotation-packets"

ROLE_USERS = {
    "B": "ssf13546",
    "C": "my-mayun",
    "E": "gmr11d4j7i",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def assigned_annotators(case: dict[str, Any]) -> tuple[str, str]:
    category = case["category"]
    if category in {"fact_qa", "visual"}:
        return ("B", "E")
    if category == "refusal":
        return ("C", "E")
    if category == "cross_knowledge":
        return ("B", "C")
    if category == "computation_short_answer":
        return ("C", "B") if case["mode"] == "training" else ("C", "E")
    raise ValueError(f"unsupported category: {category}")


def _packet_row(
    case: dict[str, Any],
    artifact: dict[str, Any],
    annotator_id: str,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "annotator_id": annotator_id,
        "critical": case["critical"],
        "query": case["query"],
        "student_answer": case.get("student_answer"),
        "expected_behavior": case["expected_behavior"],
        "expected_evidence": case["expected_evidence"],
        "scoring_policy": case["scoring_policy"],
        "system_behavior": artifact.get("model_behavior"),
        "system_response": artifact.get("response", ""),
        "system_citations": artifact.get("citations", []),
        "system_score": artifact.get("score"),
        "judgments": {
            "answer": "na",
            "citation": "na",
            "refusal": "na",
            "grading": "na",
        },
        "notes": "",
    }


def create_packets(cases_path: Path, artifacts_path: Path, output_dir: Path) -> None:
    cases = _load_jsonl(cases_path)
    artifacts = {
        row["case_id"]: row
        for row in _load_jsonl(artifacts_path)
    }
    missing = [case["case_id"] for case in cases if case["case_id"] not in artifacts]
    if missing:
        raise ValueError(f"missing run artifacts for: {', '.join(missing)}")

    packets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        for annotator_id in assigned_annotators(case):
            packets[annotator_id].append(
                _packet_row(case, artifacts[case["case_id"]], annotator_id)
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    for role, rows in sorted(packets.items()):
        username = ROLE_USERS[role]
        destination = output_dir / f"{role}-{username}.jsonl"
        destination.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )

    guide = """\
# Issue #18 私有人工标注说明

1. 每位标注者只编辑分配给自己的 JSONL 文件，保持每行一个完整 JSON 对象。
2. 根据 `scoring_policy` 和课程原始资料独立判断，不查看另一位标注者的结论。
3. 只把适用指标从 `na` 改为 `pass` 或 `fail`，并在 `notes` 写简短依据。
4. 不要通过公开 GitHub 提交或 Issue 发送本目录；其中包含模型回答与课程内容。
5. 将填写后的文件私下交给 A。A 合并后运行 `evaluate.py report`；有分歧时记录仲裁。

分工：事实/检索 B+E，综合简答 C+E，扫描/引用 B+E，训练评分 C+B，
跨知识点 B+C，拒答 C+E。
"""
    (output_dir / "README.md").write_text(guide, encoding="utf-8")

    counts = ", ".join(
        f"{role}({ROLE_USERS[role]})={len(rows)}"
        for role, rows in sorted(packets.items())
    )
    print(f"Created private annotation packets: {counts}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create private annotation packets from a real evaluation run.",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    create_packets(args.cases, args.artifacts, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
