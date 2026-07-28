"""GradingAdapter — C 的评分适配器接口与 Fake 实现。"""

from __future__ import annotations

from typing import Protocol


class GradingAdapterProtocol(Protocol):
    """C 的评分适配器接口。"""

    async def grade(
        self,
        *,
        item_id: str,
        user_answer: str,
        rubric: list[dict],
        expected_answer: str,
    ) -> dict:
        """对用户答案评分。

        Returns: dict matching GradeResultPrivate contract schema
          {score, max_score, step_scores, confidence, review_required}
        """
        ...


class FakeGradingAdapter:
    """模拟 C 的评分行为。

    场景:
    - correct: 满分
    - partial: 部分得分
    - incorrect: 0 分
    - error: 抛出异常（测试恢复）
    """

    def __init__(self, *, scenario: str = "correct", score: float | None = None):
        self._scenario = scenario
        self._score = score
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    async def grade(
        self,
        *,
        item_id: str,  # noqa: ARG002
        user_answer: str,
        rubric: list[dict],
        expected_answer: str,  # noqa: ARG002
    ) -> dict:
        self._call_count += 1

        if self._scenario == "error":
            raise RuntimeError("Grading adapter internal error")

        max_score = sum(r.get("max_score", 0) for r in rubric)

        if self._scenario == "correct":
            score = self._score if self._score is not None else max_score
        elif self._scenario == "partial":
            score = self._score if self._score is not None else max_score * 0.5
        else:  # incorrect
            score = 0.0

        return {
            "score": score,
            "max_score": max_score,
            "step_scores": [
                {
                    "rubric_item_id": r["id"],
                    "status": _status_for_score(score, max_score),
                    "score": score / len(rubric) if rubric else 0,
                    "feedback": f"评分维度: {r.get('description', 'N/A')}",
                }
                for r in rubric
            ],
            "confidence": 0.95 if self._scenario == "correct" else 0.6,
            "review_required": self._scenario != "correct",
        }


def _status_for_score(score: float, max_score: float) -> str:
    if max_score == 0:
        return "not_met"
    ratio = score / max_score
    if ratio >= 0.9:
        return "met"
    if ratio >= 0.3:
        return "partial"
    return "not_met"
