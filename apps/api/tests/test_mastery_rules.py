"""Mastery Rules 表驱动测试 — 确定性纯函数，无 DB 依赖。"""

from __future__ import annotations

import pytest

from apps.api.services.mastery_rules import (
    INITIAL_MASTERY,
    MASTERED_THRESHOLD,
    compute_difficulty_adjustment,
    compute_mastery,
    compute_mastery_status,
    compute_streak_update,
    initial_mastery,
    is_gradable,
    should_create_wrong_book,
)

# ============================================================
# compute_mastery
# ============================================================

@pytest.mark.parametrize("old,ratio,expected", [
    (0.5, 1.0, 0.65),    # baseline
    (0.5, 0.0, 0.35),    # wrong answer drops
    (0.0, 1.0, 0.3),     # from zero
    (1.0, 0.0, 0.7),     # from full
    (0.0, 0.0, 0.0),     # floor
    (1.0, 1.0, 1.0),     # ceiling
    (0.95, 1.0, 0.965),  # near ceiling (clamped to 1? no, 0.7*0.95+0.3=0.965)
    (0.5, 0.8, 0.59),    # threshold boundary
    (0.8, 0.8, 0.8),     # stable
    (0.2, 0.5, 0.29),    # fractional
])
def test_compute_mastery(old, ratio, expected) -> None:
    assert compute_mastery(old, ratio) == pytest.approx(expected, abs=0.005)


def test_compute_mastery_clamp() -> None:
    """验证值在 [0, 1] 范围内。"""
    for old in (0.0, 0.5, 1.0):
        for ratio in (0.0, 0.5, 1.0):
            result = compute_mastery(old, ratio)
            assert 0.0 <= result <= 1.0


# ============================================================
# should_create_wrong_book
# ============================================================

@pytest.mark.parametrize("ratio,uncertain,expected", [
    (0.8, False, False),   # exactly at threshold → no wrong book
    (0.79, False, True),   # just below → wrong book
    (0.9, True, True),     # uncertain → always wrong book
    (0.0, False, True),    # totally wrong
    (1.0, False, False),   # perfect
    (0.5, False, True),    # half correct
])
def test_should_create_wrong_book(ratio, uncertain, expected) -> None:
    assert should_create_wrong_book(ratio, uncertain=uncertain) == expected


# ============================================================
# compute_mastery_status
# ============================================================

@pytest.mark.parametrize("scores,expected", [
    ([True, True], "mastered"),           # two consecutive ≥0.8
    ([True], "pending"),                   # only one
    ([True, True, True], "mastered"),     # three
    ([True, True, False], "pending"),     # mastered then failed
    ([False, True, True], "mastered"),    # failed then two good
    ([False], "pending"),                 # single fail
    ([], "pending"),                      # empty
])
def test_compute_mastery_status(scores, expected) -> None:
    assert compute_mastery_status(scores) == expected


# ============================================================
# compute_difficulty_adjustment
# ============================================================

@pytest.mark.parametrize("scores,current,expected", [
    ([True, True], 2, 3),          # two good → +1
    ([False, False], 2, 1),        # two bad → -1
    ([True, True], 3, 3),          # at max, cannot increase
    ([False, False], 1, 1),        # at min, cannot decrease
    ([True], 2, 2),                # only one → no change
    ([True, True], 1, 2),          # from 1 to 2
    ([False, True], 2, 2),         # mixed → no change
    ([True, True, True], 2, 3),    # three good → +1 (only checks last 2)
])
def test_compute_difficulty_adjustment(scores, current, expected) -> None:
    assert compute_difficulty_adjustment(scores, current) == expected


# ============================================================
# compute_streak_update
# ============================================================

@pytest.mark.parametrize("correct,current,expected", [
    (True, 0, 1),
    (True, 5, 6),
    (False, 5, 0),
    (False, 0, 0),
    (True, 10, 11),
])
def test_compute_streak_update(correct, current, expected) -> None:
    assert compute_streak_update(correct, current) == expected


# ============================================================
# initial_mastery
# ============================================================

def test_initial_mastery() -> None:
    assert initial_mastery() == 0.5
    assert INITIAL_MASTERY == 0.5


# ============================================================
# is_gradable
# ============================================================

@pytest.mark.parametrize("confidence,review,expected", [
    (0.0, False, False),   # zero confidence → not gradable
    (0.5, False, True),    # positive confidence → gradable
    (0.9, True, False),    # review required → not gradable
    (0.0, True, False),    # both bad → not gradable
    (1.0, False, True),    # perfect → gradable
])
def test_is_gradable(confidence, review, expected) -> None:
    assert is_gradable(confidence, review) == expected


# ============================================================
# Constants
# ============================================================

def test_mastered_threshold() -> None:
    assert MASTERED_THRESHOLD == 0.8
