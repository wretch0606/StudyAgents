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

PROMPT_VERSIONS = {
    "coordinator": "coordinator-v1",
    "knowledge": "knowledge-v1.1",
    "evaluator": "evaluator-qa-v1",
}
