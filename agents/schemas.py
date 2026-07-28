"""
Agent 输出 Pydantic Schema — V1.0

D 的 ModelGateway.invoke_structured() 要求 output_schema 为 Pydantic BaseModel。
每个 Agent 节点对应一个输出 Schema。
"""
from __future__ import annotations

try:
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError("请安装 pydantic: pip install pydantic")

EVIDENCE_REASON_DESCRIPTION = (
    "sufficient | no_results | topic_mismatch | missing_condition | "
    "conflicting | staff_only | image_unavailable"
)


# ═══════════════════════════════════════════════════════
# 协调 Agent → CoordinatorDecision
# ═══════════════════════════════════════════════════════


class CoordinatorFilters(BaseModel):
    chapter_ids: list[str] = Field(default_factory=list, description="章节 ID 列表")
    question_types: list[str] | None = Field(default=None, description="题型限制")
    difficulty: int | None = Field(default=None, ge=1, le=3, description="难度 1-3")


class CoordinatorDecision(BaseModel):
    """协调 Agent 的路由决策输出"""
    intent: str = Field(..., description="qa_ask | practice | appeal | other")
    normalized_query: str = Field(..., min_length=1, description="标准化后的查询文本")
    filters: CoordinatorFilters = Field(default_factory=CoordinatorFilters)
    next_node: str = Field(..., description="knowledge | refusal | error")
    public_summary: str = Field(..., min_length=1, max_length=200, description="中文公开摘要")


# ═══════════════════════════════════════════════════════
# 知识 Agent → KnowledgeResult
# ═══════════════════════════════════════════════════════


class KnowledgeItemSchema(BaseModel):
    fact: str = Field(..., min_length=1, description="结构化的知识点描述")
    source_ref_ids: list[str] = Field(..., min_length=1, description="关联的 SourceRef ID 列表")
    knowledge_point_ids: list[str] = Field(default_factory=list)


class KnowledgeResult(BaseModel):
    """知识 Agent 的证据整理输出"""
    sufficient: bool = Field(..., description="证据是否足以回答问题")
    reason: str = Field(
        ...,
        description=EVIDENCE_REASON_DESCRIPTION,
    )
    knowledge_items: list[KnowledgeItemSchema] = Field(default_factory=list)
    selected_source_ref_ids: list[str] = Field(default_factory=list)
    requires_vision: bool = Field(default=False)
    public_summary: str = Field(..., min_length=1, max_length=200)


# ═══════════════════════════════════════════════════════
# 评测 Agent（问答模式）→ QAAnswer
# ═══════════════════════════════════════════════════════


class Citation(BaseModel):
    document_name: str
    page_number: int = Field(ge=1)
    question_no: str | None = None
    excerpt_snippet: str = Field(..., max_length=80, description="关键摘录前 80 字")


class QAAnswer(BaseModel):
    """评测讲解 Agent（问答模式）的输出"""
    answer: str = Field(..., min_length=1, description="完整回答文本（Markdown + LaTeX）")
    citations: list[Citation] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)
    confidence_note: str = Field(default="", description="不确定或局限时说明")
    public_summary: str = Field(..., min_length=1, max_length=200)


# ═══════════════════════════════════════════════════════
# 提示词版本常量
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
# 出题 Agent → GeneratedQuestionPrivate
# ═══════════════════════════════════════════════════════


class RubricItem(BaseModel):
    """评分点"""
    id: str = Field(..., pattern=r"^R\d+$", description="评分点 ID，如 R1, R2")
    description: str = Field(..., min_length=1, description="评分点描述")
    max_score: float = Field(..., gt=0, description="该评分点满分")
    source_ref_ids: list[str] = Field(..., min_length=1, description="引用证据 ID 列表")


class QuestionPrivate(BaseModel):
    """题目私有部分——严禁暴露到学生端"""
    expected_answer: str = Field(..., min_length=1, description="标准答案（LaTeX 公式用 $...$ 或 $$...$$）")
    rubric: list[RubricItem] = Field(..., min_length=1, description="分步评分规则")


class GeneratedQuestionPrivate(BaseModel):
    """出题 Agent 完整输出（C 内部使用）"""
    question_id: str = Field(..., description="题目 UUID")
    source_kind: str = Field(..., description="past_exam | generated_variant")
    question_type: str = Field(..., description="choice | fill_blank | calculation | short_answer")
    difficulty: int = Field(..., ge=1, le=3)
    stem: str = Field(..., min_length=1, description="题干（LaTeX 公式用 $...$ 或 $$...$$）")
    options: list[dict] = Field(default_factory=list, description="选择题选项")
    knowledge_point_ids: list[str] = Field(default_factory=list)
    source_refs: list[dict] = Field(default_factory=list, description="题目引用的证据")
    private: QuestionPrivate = Field(..., description="🚫 私有——标准答案和评分点")
    confidence: float = Field(..., ge=0.0, le=1.0, description="出题置信度（≥0.8 可投放）")
    public_summary: str = Field(..., min_length=1, max_length=200)


# ═══════════════════════════════════════════════════════
# 评测 Agent（训练模式）→ GradeResultPrivate
# ═══════════════════════════════════════════════════════


class StepScore(BaseModel):
    """分步评分"""
    rubric_item_id: str = Field(..., description="对应评分点 ID")
    status: str = Field(..., description="met | partial | not_met")
    score: float = Field(..., ge=0, description="该步得分")
    feedback: str = Field(..., min_length=1, description="分步反馈")


class GradeResultPrivate(BaseModel):
    """评测讲解 Agent（训练模式）完整输出"""
    score: float = Field(..., ge=0, description="最终得分（服务端累加校验）")
    max_score: float = Field(..., gt=0)
    step_scores: list[StepScore] = Field(..., min_length=1, description="分步评分详情")
    explanation: str = Field(default="", description="参考讲解")
    source_ref_ids: list[str] = Field(default_factory=list, description="讲解引用的证据 ID")
    confidence: float = Field(..., ge=0.0, le=1.0, description="评分置信度（<0.7 进入复核）")
    review_required: bool = Field(default=False, description="是否需要管理员复核")
    public_summary: str = Field(..., min_length=1, max_length=200)


# ═══════════════════════════════════════════════════════
# 训练公开反馈（学生可见）→ PracticeFeedback
# ═══════════════════════════════════════════════════════


class StepFeedbackPublic(BaseModel):
    """学生可见的分步反馈（不含评分点 ID 和分值）"""
    status: str = Field(..., description="met | partial | not_met")
    text: str = Field(..., min_length=1, description="反馈文本")


class PracticeFeedback(BaseModel):
    """学生可见的评分反馈"""
    score: float = Field(..., ge=0)
    max_score: float = Field(..., gt=0)
    score_ratio: float = Field(..., ge=0.0, le=1.0)
    verdict: str = Field(..., description="中文评价如'优秀''需改进'")
    steps: list[StepFeedbackPublic] = Field(default_factory=list, description="分步反馈（不含分值和评分点ID）")
    explanation: str = Field(default="", description="参考讲解")
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    review_required: bool = Field(default=False)


# ═══════════════════════════════════════════════════════
# 提示词版本常量
# ═══════════════════════════════════════════════════════

PROMPT_VERSIONS = {
    "coordinator": "coordinator-v1",
    "knowledge": "knowledge-v1",
    "evaluator": "evaluator-qa-v1",
    "questioner": "questioner-v1",
    "evaluator_practice": "evaluator-practice-v1",
}
