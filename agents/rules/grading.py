"""
客观题确定性评分规则 — V1.0

不调用 LLM，纯规则判定，置信度 1.0。
对应开发文档 7.4 节。
"""
from __future__ import annotations

import re
from typing import Any, Optional


# ═══════════════════════════════════════════════════════
# 选择题
# ═══════════════════════════════════════════════════════


def grade_choice(user_answer: str, expected: str, max_score: int = 0) -> dict:
    """
    选择题评分：选项 ID 精确比较。

    Args:
        user_answer: 用户提交的选项 ID（如 "A"）
        expected: 标准答案的选项 ID
        max_score: 满分（未使用，选择题只有对/错）

    Returns:
        {"score": int, "max_score": int, "confidence": 1.0, "met": bool}
    """
    score = max_score if user_answer.strip().upper() == expected.strip().upper() else 0
    is_correct = user_answer.strip().upper() == expected.strip().upper()
    return {
        "score": score,
        "max_score": max_score,
        "confidence": 1.0,
        "met": is_correct,
        "feedback": "选项正确" if is_correct else f"选项错误，正确答案为 {expected}",
    }


# ═══════════════════════════════════════════════════════
# 填空题
# ═══════════════════════════════════════════════════════


def normalize_answer(text: str) -> str:
    """
    规范化文本：全角→半角、去空白、统一大小写、数值精度对齐。

    用于填空题答案比对。
    """
    # 全角数字和字母 → 半角
    result = ""
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result += chr(code - 0xFEE0)
        elif code == 0x3000:  # 全角空格
            result += " "
        else:
            result += ch
    # 去多余空白
    result = re.sub(r"\s+", " ", result).strip()
    # 统一大小写
    result = result.lower()
    return result


def grade_fill_blank(
    user_answer: str,
    expected: str,
    acceptable_forms: Optional[list[str]] = None,
    max_score: int = 0,
) -> dict:
    """
    填空题评分：规范化后按答案规则比较。

    Args:
        user_answer: 用户提交的答案
        expected: 标准答案
        acceptable_forms: 可接受的等价形式列表（在题目评分规则中预定义）
        max_score: 满分

    Returns:
        {"score": int, "max_score": int, "confidence": 1.0, "met": bool}
    """
    norm_user = normalize_answer(user_answer)
    norm_expected = normalize_answer(expected)

    # 精确匹配
    if norm_user == norm_expected:
        return {"score": max_score, "max_score": max_score, "confidence": 1.0, "met": True, "feedback": "答案正确"}

    # 等价形式匹配
    if acceptable_forms:
        for form in acceptable_forms:
            if norm_user == normalize_answer(form):
                return {"score": max_score, "max_score": max_score, "confidence": 1.0, "met": True, "feedback": "答案正确（等价形式）"}

    # 数值精度匹配：尝试提取数值比较
    user_num = _extract_number(norm_user)
    expected_num = _extract_number(norm_expected)
    if user_num is not None and expected_num is not None:
        # 相对误差 < 1%
        if expected_num != 0 and abs(user_num - expected_num) / abs(expected_num) < 0.01:
            return {"score": max_score, "max_score": max_score, "confidence": 1.0, "met": True, "feedback": "答案正确（数值在容许误差内）"}
        if abs(user_num - expected_num) < 1e-9:
            return {"score": max_score, "max_score": max_score, "confidence": 1.0, "met": True, "feedback": "答案正确"}

    return {"score": 0, "max_score": max_score, "confidence": 1.0, "met": False, "feedback": "答案不正确"}


def _extract_number(text: str) -> Optional[float]:
    """从文本中提取数值（含科学计数法）"""
    match = re.search(r"[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?", text)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


# ═══════════════════════════════════════════════════════
# 主观题分步评分校验
# ═══════════════════════════════════════════════════════


def validate_step_scores(step_scores: list[dict], rubric: list[dict], max_total: int) -> dict:
    """
    校验 LLM 返回的分步评分是否在上限内。

    Args:
        step_scores: LLM 返回的分步评分 [{"rubric_item_id": "R1", "status": "met", "score": 4}, ...]
        rubric: 题目评分规则 [{"id": "R1", "max_score": 4}, ...]
        max_total: 卷面总分上限

    Returns:
        {"valid": bool, "total": float, "violations": list[str]}
    """
    rubric_max = {r["id"]: r["max_score"] for r in rubric}
    total = 0.0
    violations = []

    for step in step_scores:
        rid = step.get("rubric_item_id", "")
        score = step.get("score", 0)
        max_for_item = rubric_max.get(rid)

        if max_for_item is None:
            violations.append(f"评分项 {rid} 不在题目评分规则中")
            continue
        if score < 0:
            violations.append(f"评分项 {rid} 分数 {score} < 0")
        if score > max_for_item:
            violations.append(f"评分项 {rid} 分数 {score} 超过上限 {max_for_item}")
        total += min(max(0, score), max_for_item)

    if total > max_total:
        violations.append(f"总分 {total} 超过卷面上限 {max_total}")

    return {
        "valid": len(violations) == 0,
        "total": min(total, max_total),
        "violations": violations,
    }


# ═══════════════════════════════════════════════════════
# 掌握度更新（确定性公式）
# ═══════════════════════════════════════════════════════


def update_mastery(old_mastery: float, score_ratio: float) -> float:
    """
    更新知识点掌握度。

    公式（开发文档 7.5 节）：
      new_mastery = clamp(0, 1, 0.7 × old_mastery + 0.3 × score_ratio)

    Args:
        old_mastery: 当前掌握度（0-1）
        score_ratio: 本轮得分率（0-1）

    Returns:
        新掌握度（0-1）
    """
    new_mastery = 0.7 * old_mastery + 0.3 * score_ratio
    return max(0.0, min(1.0, new_mastery))


def adjust_difficulty(
    current_difficulty: int,
    recent_score_ratios: list[float],
    threshold_high: float = 0.8,
    threshold_low: float = 0.5,
) -> int:
    """
    根据最近表现调整难度。

    规则（开发文档 7.5 节）：
    - 连续两次 ≥ 80% → 上调一级
    - 连续两次 < 50% → 下调一级
    - 其余保持
    - 难度限制在 1-3
    """
    if len(recent_score_ratios) < 2:
        return current_difficulty

    last_two = recent_score_ratios[-2:]
    if all(r >= threshold_high for r in last_two):
        return min(3, current_difficulty + 1)
    if all(r < threshold_low for r in last_two):
        return max(1, current_difficulty - 1)
    return current_difficulty
