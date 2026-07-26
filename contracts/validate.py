"""
契约校验脚本 — 无需安装外部依赖
用法: python contracts/validate.py
校验: Schema 合法性、Mock 示例是否符合 Schema、隐私边界
"""
import json
import os
import re
import sys
from typing import Any, Optional

# 强制 UTF-8 输出
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 颜色 + 标签 ───────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
CHECK = "[OK]"
CROSS = "[FAIL]"
ARROW = "->"
WARN_TAG = "[WARN]"

passed = 0
failed = 0

def ok(msg: str):
    global passed
    passed += 1
    print(f"  {GREEN}{CHECK}{RESET} {msg}")

def err(msg: str):
    global failed
    failed += 1
    print(f"  {RED}{CROSS}{RESET} {msg}")

def info(msg: str):
    print(f"  {CYAN}{ARROW}{RESET} {msg}")

def warn(msg: str):
    print(f"  {YELLOW}{WARN_TAG}{RESET} {msg}")


# ═══════════════════════════════════════════════════════
# 基础加载
# ═══════════════════════════════════════════════════════

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)


def load_json(path: str) -> Optional[dict]:
    """加载 JSON 文件，编码错误或格式错误时报错。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        err(f"{path}: JSON 格式错误 — {e}")
        return None
    except FileNotFoundError:
        err(f"{path}: 文件不存在")
        return None


# ═══════════════════════════════════════════════════════
# Schema 校验
# ═══════════════════════════════════════════════════════

SCHEMA_META = {
    "source-ref.schema.json":           {"entity": "SourceRef",            "src": "B→C"},
    "agent-event.schema.json":          {"entity": "AgentEvent",           "src": "C→D→E (SSE)"},
    "error.schema.json":                {"entity": "ApiError",             "src": "统一错误"},
    "public-question.schema.json":      {"entity": "PublicQuestion",       "src": "C→D→E"},
    "agent-state.schema.json":          {"entity": "AgentState",           "src": "C↔D (状态图内部)"},
    "generated-question-private.schema.json": {"entity": "GeneratedQuestionPrivate", "src": "C 内部"},
    "grade-result-private.schema.json": {"entity": "GradeResultPrivate",   "src": "C 内部"},
}


def validate_schema_meta(schema: dict, filename: str) -> bool:
    """校验 schema 文件的元信息完整性。"""
    all_ok = True
    for key in ["$schema", "$id", "title", "type", "properties"]:
        if key not in schema:
            err(f"{filename}: 缺少必需字段 '{key}'")
            all_ok = False
    if schema.get("type") != "object":
        err(f"{filename}: type 必须为 'object'")
        all_ok = False
    return all_ok


PRIVACY_SENSITIVE = frozenset({
    "expected_answer", "answer_private", "rubric", "rubric_private",
    "private_content", "step_scores", "private", "question_private",
    "grade_private", "private_evidence"
})


def deep_check_privacy(obj: Any, path: str = "$") -> int:
    """递归扫描 JSON，报告隐私字段泄露位置。返回泄露次数。"""
    leaks = 0
    if isinstance(obj, dict):
        for key in obj:
            current = f"{path}.{key}"
            if key.lower().replace("_", "") in {k.replace("_", "") for k in PRIVACY_SENSITIVE}:
                # 允许 $$privacy_check 自述块和 $comment 说明
                if not current.startswith("$.$$") and not current.endswith("_hidden"):
                    err(f"隐私泄露: {current} 不应出现在公开响应中")
                    leaks += 1
            deep_check_privacy(obj[key], current)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            deep_check_privacy(item, f"{path}[{i}]")
    return leaks


# ═══════════════════════════════════════════════════════
# 简易 JSON Schema 校验器
# ═══════════════════════════════════════════════════════

def validate_against_schema(instance: Any, schema: dict, path: str = "$") -> int:
    """简易 JSON Schema 校验。返回错误数。"""
    errors = 0

    if "enum" in schema:
        if instance not in schema["enum"]:
            err(f"{path}: 值 '{instance}' 不在枚举 {schema['enum']} 中")
            errors += 1

    if "const" in schema:
        if instance != schema["const"]:
            err(f"{path}: 值 '{instance}' 不等于常量 '{schema['const']}'")
            errors += 1

    if "type" in schema:
        expected = schema["type"]
        errors += _check_type(instance, expected, path)

    if "required" in schema and isinstance(instance, dict):
        for req in schema["required"]:
            if req not in instance:
                err(f"{path}: 缺少必填字段 '{req}'")
                errors += 1

    if "properties" in schema and isinstance(instance, dict):
        for prop, prop_schema in schema["properties"].items():
            if prop in instance:
                errors += validate_against_schema(instance[prop], prop_schema, f"{path}.{prop}")

    if "items" in schema and isinstance(instance, list):
        item_schema = schema["items"]
        for i, item in enumerate(instance):
            errors += validate_against_schema(item, item_schema, f"{path}[{i}]")

    if "minLength" in schema and isinstance(instance, str):
        if len(instance) < schema["minLength"]:
            err(f"{path}: 字符串长度 {len(instance)} < minLength {schema['minLength']}")
            errors += 1

    if "maxLength" in schema and isinstance(instance, str):
        if len(instance) > schema["maxLength"]:
            warn(f"{path}: 字符串长度 {len(instance)} > maxLength {schema['maxLength']}")

    if "minimum" in schema and isinstance(instance, (int, float)):
        if instance < schema["minimum"]:
            err(f"{path}: {instance} < minimum {schema['minimum']}")
            errors += 1

    if "maximum" in schema and isinstance(instance, (int, float)):
        if instance > schema["maximum"]:
            err(f"{path}: {instance} > maximum {schema['maximum']}")
            errors += 1

    if "pattern" in schema and isinstance(instance, str):
        if not re.match(schema["pattern"], instance):
            warn(f"{path}: '{instance}' 不匹配 pattern '{schema['pattern']}'")

    return errors


def _check_type(instance: Any, expected: Any, path: str, silent: bool = False) -> int:
    """校验类型。silent=True 时不打印错误（用于 union 分支探测）。"""
    type_map = {
        "string": str, "integer": int, "number": (int, float),
        "boolean": bool, "object": dict, "array": list, "null": type(None),
    }
    if isinstance(expected, list):
        # {"type": ["string", "null"]} → union，逐个探测
        valid = any(_check_type(instance, t, path, silent=True) == 0 for t in expected)
        if not valid:
            err(f"{path}: type {type(instance).__name__} not in {expected}")
            return 1
        return 0
    py_type = type_map.get(expected)
    if py_type is None:
        return 0  # unknown type, skip
    if not isinstance(instance, py_type):
        if not silent:
            err(f"{path}: expected {expected}, got {type(instance).__name__}")
        return 1
    return 0


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════

def main():
    global passed, failed

    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  StudyAgents Contract Validation{RESET}")
    print(f"{CYAN}{'='*60}{RESET}\n")

    # ── Phase 1: 加载并校验所有 Schema 文件 ──
    print(f"{YELLOW}[1/4] Schema 元信息校验{RESET}")
    schemas = {}
    for filename, meta in SCHEMA_META.items():
        path = os.path.join(BASE, filename)
        data = load_json(path)
        if data is None:
            continue
        schemas[filename] = data
        info(f"{filename} ({meta['entity']} · {meta['src']})")
        validate_schema_meta(data, filename)
        ok(f"{filename} — 元信息完整")

    print(f"\n{YELLOW}[2/4] Mock 文件加载{RESET}")
    mock_dir = os.path.join(BASE, "mock")
    mocks = {}
    for fname in sorted(os.listdir(mock_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(mock_dir, fname)
        data = load_json(path)
        if data is None:
            continue
        mocks[fname] = data
        ok(f"mock/{fname} — 已加载")

    print(f"\n{YELLOW}[3/4] Mock 隐私边界扫描{RESET}")
    privacy_map = {
        "training-question.json": "提交答案前的公开题目（最关键）",
        "grading-result.json":   "评分公开反馈",
        "qa-success.json":       "问答成功响应",
        "qa-refusal.json":       "拒答响应",
        "failure-model-timeout.json": "失败场景",
    }
    for fname, description in privacy_map.items():
        if fname in mocks:
            info(f"mock/{fname} — {description}")
            leaks = deep_check_privacy(mocks[fname])
            if leaks == 0:
                ok(f"mock/{fname} — 无隐私泄露")
            else:
                err(f"mock/{fname} — 发现 {leaks} 处泄露")

    print(f"\n{YELLOW}[4/4] Mock 按 Schema 字段校验{RESET}")

    # ── 逐个 mock 场景做基本字段校验 ──
    for fname, mock in mocks.items():
        info(f"mock/{fname} — 字段校验")

        # 1) training-question → public-question.schema.json
        if fname == "training-question.json" and "public-question.schema.json" in schemas:
            pq = mock.get("public_question", {})
            errors = validate_against_schema(pq, schemas["public-question.schema.json"])
            if errors == 0:
                ok("public_question 符合 PublicQuestion schema")
            # 显式确认不含私有字段
            forbidden = ["expected_answer", "rubric", "answer_private", "private_content"]
            for f in forbidden:
                if f in pq:
                    err(f"public_question 含禁止字段 '{f}'")

        # 2) qa-success → agent-event (校验内嵌 events)
        if fname in ("qa-success.json", "qa-refusal.json", "failure-model-timeout.json", "training-question.json"):
            events = mock.get("public_response", {}).get("agent_events", [])
            events_alt = mock.get("related_agent_events", [])
            all_events = events + events_alt
            if all_events and "agent-event.schema.json" in schemas:
                for evt in all_events:
                    errors = validate_against_schema(evt, schemas["agent-event.schema.json"])
                if errors == 0:
                    ok(f"agent_events ({len(all_events)} 条) 符合 AgentEvent schema")
                else:
                    err(f"agent_events 有 {errors} 处不符")

        # 3) failure-model-timeout → error.schema.json
        if fname == "failure-model-timeout.json" and "error.schema.json" in schemas:
            error_obj = mock.get("public_response", {}).get("error")
            if error_obj:
                errors = validate_against_schema(error_obj, schemas["error.schema.json"])
                if errors == 0:
                    ok("error 符合 ApiError schema")

        # 4) qa-success / qa-refusal → source-ref.schema.json
        if fname in ("qa-success.json", "qa-refusal.json"):
            refs = mock.get("public_response", {}).get("source_refs", [])
            if refs and "source-ref.schema.json" in schemas:
                for ref in refs:
                    errors = validate_against_schema(ref, schemas["source-ref.schema.json"])
                if errors == 0:
                    ok(f"source_refs ({len(refs)} 条) 符合 SourceRef schema")

    # ── 总结 ──
    print(f"\n{CYAN}{'='*60}{RESET}")
    total = passed + failed
    pct = 100 * passed // total if total > 0 else 0
    if failed == 0:
        print(f"{GREEN}  ALL PASSED{RESET}  {passed}/{total} checks ({pct}%)")
    else:
        print(f"{RED}  {failed} FAILED{RESET}  {passed}/{total} checks ({pct}%)")
    print(f"{CYAN}{'='*60}{RESET}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
