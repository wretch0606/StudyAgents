"""Practice API 公开 DTO — 严格对齐前端冻结契约 api(6).ts 第 7/8/9 节。

白名单控制：禁止 expected_answer / rubric / step_scores / 私有证据块。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ============================================================
# 共享枚举 / 子类型
# ============================================================

PracticeSessionStatus = Literal["active", "completed", "cancelled"]
SourceKind = Literal["past_exam", "generated_variant"]
QuestionType = Literal["choice", "fill_blank", "calculation", "short_answer"]
DifficultyLevel = Literal[1, 2, 3]


class PracticeProgress(BaseModel):
    """训练进度 — 对齐 api(6).ts PracticeProgress。"""
    current: int
    total: int


class OptionItem(BaseModel):
    """客观题选项 — 对齐 api(6).ts OptionItem。"""
    id: str
    text: str


# ============================================================
# 题目
# ============================================================

class PracticeItem(BaseModel):
    """公开训练题目 — 对齐 api(6).ts PracticeItem。

    仅含题干/选项/进度/来源标签，不含 answer/rubric/private_snapshot。
    """
    model_config = ConfigDict(extra="forbid")

    item_id: str
    question_version: str
    order_no: int
    source_kind: str
    question_type: str
    difficulty: int
    stem: str
    options: list[OptionItem] = Field(default_factory=list)
    source_label: str = ""
    progress: PracticeProgress


# ============================================================
# 训练会话配置（请求体）
# ============================================================

class PracticeSessionConfig(BaseModel):
    """创建训练配置 — 对齐 api(6).ts PracticeSessionConfig。"""
    chapter_ids: list[str] = Field(default_factory=list)
    knowledge_point_ids: list[str] = Field(default_factory=list)
    question_types: list[str] = Field(default_factory=lambda: ["choice"])
    difficulty: int = Field(default=2, ge=1, le=3)
    target_count: int = Field(default=5, ge=3, le=20)


# ============================================================
# ActiveRunRef
# ============================================================

class ActiveRunRef(BaseModel):
    """异步运行引用 — 对齐 api(6).ts ActiveRunRef。"""
    run_id: str
    event_url: str


# ============================================================
# 训练会话（响应体）
# ============================================================

class PracticeSession(BaseModel):
    """训练会话 — 对齐 api(6).ts PracticeSession。"""
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    filters: PracticeSessionConfig
    target_count: int
    status: str
    current_item: PracticeItem | None = None
    progress: PracticeProgress
    active_run: ActiveRunRef | None = None
    created_at: datetime | str
    updated_at: datetime | str


# ============================================================
# 创建训练响应（可辨识联合）
# ============================================================

class CreatePracticeSessionResponse(BaseModel):
    """创建训练响应 — 对齐 api(6).ts CreatePracticeSessionResponse。"""
    model_config = ConfigDict(extra="forbid")

    state: Literal["ready", "generating"]
    session: PracticeSession
    run_id: str | None = None
    event_url: str | None = None


# ============================================================
# 提交答案
# ============================================================

class AnswerSubmissionRequest(BaseModel):
    """提交答案请求 — 对齐 api(6).ts AnswerSubmission。"""
    item_id: str
    question_version: str
    raw_text: str | None = None
    selected_option_ids: list[str] | None = None
    is_uncertain: bool = False


class SubmitAnswerResponse(BaseModel):
    """提交答案响应 — 对齐 api(6).ts SubmitAnswerResponse。"""
    model_config = ConfigDict(extra="forbid")

    run_id: str
    event_url: str


# ============================================================
# 结束训练
# ============================================================

class FinishPracticeSessionResponse(BaseModel):
    """结束训练响应 — 对齐 api(6).ts FinishPracticeSessionResponse。"""
    model_config = ConfigDict(extra="forbid")

    session_id: str
    status: Literal["completed", "cancelled"]
    summary_url: str


# ============================================================
# 训练总结
# ============================================================

class KnowledgePointPerformance(BaseModel):
    """知识点表现 — 对齐 api(6).ts KnowledgePointPerformance。"""
    knowledge_point_id: str
    knowledge_point_name: str
    mastery: float
    mastery_change: float


class GradeInfo(BaseModel):
    """公开评分信息 — 对齐 api(6).ts GradeInfo 的公开子集。"""
    model_config = ConfigDict(extra="forbid")

    id: str
    answer_id: str
    score: float
    max_score: float
    confidence: float
    review_required: bool


class SessionSummary(BaseModel):
    """训练总结 — 对齐 api(6).ts SessionSummary。"""
    model_config = ConfigDict(extra="forbid")

    session_id: str
    total_score: float
    total_max_score: float
    grades: list[GradeInfo] = Field(default_factory=list)
    knowledge_point_performance: list[KnowledgePointPerformance] = Field(
        default_factory=list,
    )
    wrong_book_entry_ids: list[str] = Field(default_factory=list)
    suggestion: str | None = None


# ============================================================
# 分页列表
# ============================================================

class PracticeSessionListParams(BaseModel):
    """训练历史查询参数 — 对齐 api(6).ts PracticeSessionListParams。"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    status: str | None = None
    chapter_id: str | None = None
    knowledge_point_id: str | None = None
    started_from: str | None = None
    started_to: str | None = None
