"""Grading API 公开 DTO — 提交答案和评分反馈。

白名单控制：禁止 step_scores、rubric、expected_answer 等私有字段。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SubmitAnswerRequest(BaseModel):
    """POST /api/training/{session_id}/submit 请求体。"""

    item_id: str
    answer_text: str
    question_version: str = "1.0"


class SubmitAnswerResponse(BaseModel):
    """公开评分反馈 — 不含 raw step_scores 或私有评分维度。"""

    model_config = ConfigDict(extra="forbid")

    submission_id: str
    grade_id: str
    score: float
    max_score: float
    score_ratio: float
    verdict: str
    summary: str
    step_feedback: list[str] = Field(default_factory=list)
    confidence: float
    review_required: bool
    wrong_book_created: bool = False
