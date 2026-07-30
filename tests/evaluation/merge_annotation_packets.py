"""Validate and merge private Issue #18 annotation packets."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .create_annotation_packets import assigned_annotators
except ImportError:
    from create_annotation_packets import assigned_annotators

ROOT = Path(__file__).resolve().parents[2]
EVALUATION_DIR = ROOT / "tests" / "evaluation"
DEFAULT_CASES = EVALUATION_DIR / "cases.public.jsonl"
DEFAULT_POLICIES = EVALUATION_DIR / "policies.json"
DEFAULT_OUTPUT = EVALUATION_DIR / "private" / "annotations.jsonl"
JUDGMENT_KEYS = {"answer", "citation", "refusal", "grading"}
JUDGMENT_VALUES = {"pass", "fail", "na"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_packet_line(line: str) -> tuple[dict[str, Any], bool]:
    """Parse a packet row, recovering the annotation tail if context was damaged."""
    try:
        return json.loads(line), False
    except json.JSONDecodeError as original_error:
        case_match = re.search(r'"case_id"\s*:\s*"([^"]+)', line)
        annotator_match = re.search(r'"annotator_id"\s*:\s*"([^"]+)', line)
        tail_start = line.rfind('"judgments"')
        if not case_match or not annotator_match or tail_start < 0:
            raise original_error
        try:
            tail = json.loads("{" + line[tail_start:])
        except json.JSONDecodeError:
            raise original_error
        return (
            {
                "case_id": case_match.group(1),
                "annotator_id": annotator_match.group(1),
                "judgments": tail.get("judgments"),
                "notes": tail.get("notes", ""),
            },
            True,
        )


def merge_packets(
    packet_paths: list[Path],
    cases_path: Path,
    policies_path: Path,
    output_path: Path,
) -> tuple[int, int, int]:
    cases = _load_jsonl(cases_path)
    cases_by_id = {case["case_id"]: case for case in cases}
    policies = json.loads(policies_path.read_text(encoding="utf-8"))["policies"]
    expected_pairs = {
        (case["case_id"], annotator)
        for case in cases
        for annotator in assigned_annotators(case)
    }

    rows: list[dict[str, Any]] = []
    recovered = 0
    for path in packet_paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                row, was_recovered = parse_packet_line(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name}:{line_number}: invalid JSON at column {exc.colno}"
                ) from exc
            recovered += int(was_recovered)
            row["_source"] = f"{path.name}:{line_number}"
            rows.append(row)

    errors: list[str] = []
    incomplete_judgments = 0
    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        source = row.pop("_source")
        case_id = row.get("case_id")
        annotator_id = row.get("annotator_id")
        pair = (case_id, annotator_id)
        if case_id not in cases_by_id:
            errors.append(f"{source}: unknown case_id {case_id!r}")
            continue
        if pair not in expected_pairs:
            errors.append(f"{source}: unexpected assignment {case_id}/{annotator_id}")
        if pair in seen:
            errors.append(f"{source}: duplicate assignment {case_id}/{annotator_id}")
        seen.add(pair)

        judgments = row.get("judgments")
        if not isinstance(judgments, dict) or set(judgments) != JUDGMENT_KEYS:
            errors.append(f"{source}: judgments must contain {sorted(JUDGMENT_KEYS)}")
            continue
        invalid_values = {
            value for value in judgments.values() if value not in JUDGMENT_VALUES
        }
        if invalid_values:
            errors.append(f"{source}: invalid judgments {sorted(invalid_values)}")
            continue

        case = cases_by_id[case_id]
        applicable = set(policies[case["scoring_policy"]]["dimensions"])
        applicable &= JUDGMENT_KEYS
        missing = sorted(
            metric for metric in applicable if judgments.get(metric) not in {"pass", "fail"}
        )
        if missing:
            incomplete_judgments += len(missing)

        normalized.append(
            {
                "case_id": case_id,
                "annotator_id": annotator_id,
                "judgments": judgments,
                "notes": str(row.get("notes", "")),
            }
        )

    missing_pairs = sorted(expected_pairs - seen)
    if missing_pairs:
        errors.append(
            "missing assignments: "
            + ", ".join(f"{case_id}/{role}" for case_id, role in missing_pairs)
        )
    if errors:
        raise ValueError("\n".join(errors))

    normalized.sort(key=lambda row: (row["case_id"], row["annotator_id"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in normalized
        ),
        encoding="utf-8",
    )
    return len(normalized), recovered, incomplete_judgments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and merge returned private annotation packets.",
    )
    parser.add_argument("packets", nargs="+", type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows, recovered, incomplete = merge_packets(
        args.packets,
        args.cases,
        args.policies,
        args.output,
    )
    print(
        f"Merged {rows} annotations; recovered {recovered} damaged context rows; "
        f"{incomplete} applicable judgments remain na."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
