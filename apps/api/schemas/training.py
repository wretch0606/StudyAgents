"""Training API 公开 DTO — 创建训练、获取下一题。

白名单控制：禁止 expected_answer / rubric / grade_private / 私有证据块。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CreateTrainingRequest(BaseModel):
    """POST /api/training 请求体。使用冻结默认值。"""

    chapter_ids: list[str] = Field(default_factory=list)
    question_types: list[str] = Field(default_factory=lambda: ["choice"])
    difficulty: int = Field(default=2, ge=1, le=3)
    count: int = Field(default=5, ge=3, le=20)


class CreateTrainingResponse(BaseModel):
    """训练创建响应。"""
    session_id: str
    thread_id: str
    total_questions: int


class NextQuestionResponse(BaseModel):
    """公开 DTO — 题干/选项/进度，不含答案/评分标准。"""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    order_no: int
    question_type: str
    difficulty: int
    stem: str
    options: list[dict] | None = None
    source_kind: str
    source_label: str
    question_version: str
    progress: dict  # {"current": N, "total": M}


class TrainingProgressResponse(BaseModel):
    """训练进度。"""
    session_id: str
    status: str
    total_questions: int
    current_question: int
    completed_questions: int
