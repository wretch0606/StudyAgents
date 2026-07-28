"""Mastery Rules — 确定性纯函数，无副作用、无 LLM。

掌握度计算、错题判断、难度调整、连续表现评估。
"""

from __future__ import annotations

INITIAL_MASTERY = 0.5
MASTERY_WEIGHT = 0.7  # old mastery weight in EMA
SCORE_WEIGHT = 0.3    # new score weight in EMA
MASTERED_THRESHOLD = 0.8
LOW_THRESHOLD = 0.5
MIN_DIFFICULTY = 1
MAX_DIFFICULTY = 3


def compute_mastery(old_level: float, score_ratio: float) -> float:
    """指数移动平均：new = clamp(0, 1, MASTERY_WEIGHT*old + SCORE_WEIGHT*score_ratio)。"""
    return max(0.0, min(1.0, MASTERY_WEIGHT * old_level + SCORE_WEIGHT * score_ratio))


def should_create_wrong_book(score_ratio: float, *, uncertain: bool = False) -> bool:
    """score_ratio < 0.8 或 uncertain=True → 创建/更新错题。"""
    return score_ratio < MASTERED_THRESHOLD or uncertain


def compute_mastery_status(recent_scores: list[bool]) -> str:
    """连续表现判断 mastery 状态。

    recent_scores: 最近评分是否 >= 0.8，按时间升序。
    连续两次 >= 0.8 → 'mastered'。
    已 mastered 后再次 < 0.8 → 'pending'。
    """
    if len(recent_scores) >= 2 and recent_scores[-1] and recent_scores[-2]:
        return "mastered"
    return "pending"


def compute_difficulty_adjustment(
    recent_score_ratios: list[float],
    current_difficulty: int,
    *,
    min_diff: int = MIN_DIFFICULTY,
    max_diff: int = MAX_DIFFICULTY,
) -> int:
    """根据连续表现调整难度。

    连续两次 >= MASTERED_THRESHOLD (0.8) → 难度 +1。
    连续两次 < LOW_THRESHOLD (0.5) → 难度 -1。
    不越过 [min_diff, max_diff] 边界。
    """
    new_diff = current_difficulty
    if len(recent_score_ratios) >= 2:
        a, b = recent_score_ratios[-2], recent_score_ratios[-1]
        if a >= MASTERED_THRESHOLD and b >= MASTERED_THRESHOLD:
            new_diff = current_difficulty + 1
        elif a < LOW_THRESHOLD and b < LOW_THRESHOLD:
            new_diff = current_difficulty - 1
    return max(min_diff, min(max_diff, new_diff))


def compute_streak_update(is_correct: bool, current_streak: int) -> int:
    """连续正确 → streak+1；否则重置 0。"""
    return current_streak + 1 if is_correct else 0


def initial_mastery() -> float:
    """新知识点默认掌握度为 0.5。"""
    return INITIAL_MASTERY


def is_gradable(confidence: float, review_required: bool) -> bool:
    """仅有效（confidence > 0）且非待复核的评分参与掌握度更新。"""
    return confidence > 0 and not review_required
