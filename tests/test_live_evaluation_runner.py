from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RUNNER_PATH = Path(__file__).parent / "evaluation" / "run_live.py"
SPEC = importlib.util.spec_from_file_location("run_live", RUNNER_PATH)
assert SPEC and SPEC.loader
run_live = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run_live
SPEC.loader.exec_module(run_live)

PACKETS_PATH = Path(__file__).parent / "evaluation" / "create_annotation_packets.py"
PACKETS_SPEC = importlib.util.spec_from_file_location(
    "create_annotation_packets",
    PACKETS_PATH,
)
assert PACKETS_SPEC and PACKETS_SPEC.loader
create_annotation_packets = importlib.util.module_from_spec(PACKETS_SPEC)
sys.modules[PACKETS_SPEC.name] = create_annotation_packets
PACKETS_SPEC.loader.exec_module(create_annotation_packets)


def test_explicit_scan_page_routing() -> None:
    assert run_live._explicit_scan_pages("扫描试卷第一页是什么？") == [1]
    assert run_live._explicit_scan_pages("扫描试卷第二页是什么？") == [2]
    assert run_live._explicit_scan_pages("综合前两页概括结构") == [1, 2]


def test_parse_model_json_accepts_fenced_output() -> None:
    parsed = run_live._parse_model_json(
        '```json\n{"behavior":"refuse","response":"资料不足"}\n```'
    )
    assert parsed["behavior"] == "refuse"


def test_invalid_behavior_is_recorded_as_error() -> None:
    assert run_live._validate_behavior("answer") == "answer"
    assert run_live._validate_behavior("unknown") == "error"


def test_annotation_assignments_follow_team_ownership() -> None:
    assert create_annotation_packets.assigned_annotators(
        {"category": "fact_qa", "mode": "qa"}
    ) == ("B", "E")
    assert create_annotation_packets.assigned_annotators(
        {"category": "computation_short_answer", "mode": "training"}
    ) == ("C", "B")
    assert create_annotation_packets.assigned_annotators(
        {"category": "cross_knowledge", "mode": "qa"}
    ) == ("B", "C")
