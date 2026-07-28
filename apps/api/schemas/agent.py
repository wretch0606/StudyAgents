"""Agent 运行时公开 DTO — 仅包含允许对外暴露的字段。

白名单过滤：禁止 question_private / grade_private / Prompt / 思维链。
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from apps.api.services.event_types import AgentEventType

# Size limits to prevent events from becoming full-text channels
MAX_SUMMARY_LENGTH = 2000
MAX_SOURCE_REFS = 20
MAX_EXCERPT_LENGTH = 300
MAX_DOC_NAME_LENGTH = 256
MAX_DOC_ID_LENGTH = 64
MAX_CHUNK_ID_LENGTH = 64
MAX_QUESTION_NO_LENGTH = 32
MAX_PAGE_IMAGE_URL_LENGTH = 512


# ---- 引用来源元素 ----

class SourceRef(BaseModel):
    """source_refs 中单个元素的严格 Schema — 禁止私有字段注入和全文通道绕过。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    document_id: str = Field(
        min_length=1, max_length=MAX_DOC_ID_LENGTH,
        description="资料 ID",
    )
    document_name: str = Field(
        default="", max_length=MAX_DOC_NAME_LENGTH,
        description="资料名",
    )
    page_number: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("page_number", "page_no"),
        description="页码（从 1 开始）",
    )
    question_no: str | None = Field(
        default=None, max_length=MAX_QUESTION_NO_LENGTH,
        description="题号",
    )
    chunk_id: str | None = Field(
        default=None, max_length=MAX_CHUNK_ID_LENGTH,
        description="分块 ID",
    )
    excerpt: str = Field(
        default="", max_length=MAX_EXCERPT_LENGTH,
        description="摘录文本（≤300 字）",
    )
    page_image_url: str | None = Field(
        default=None, max_length=MAX_PAGE_IMAGE_URL_LENGTH,
        description="页图 URL",
    )
    score: float = Field(default=0.0, description="检索融合分数")

    @property
    def page_no(self) -> int | None:
        """兼容旧后端调用；公开序列化统一使用 page_number。"""
        return self.page_number


# ---- C 提交的事件草稿 ----


class AgentEventDraft(BaseModel):
    """C 生成的事件草稿 — 通过 AgentEventSink.emit() 提交。

    仅允许白名单字段；extra=forbid 阻止私有字段注入。
    """

    model_config = ConfigDict(extra="forbid")

    agent: str
    event_type: AgentEventType
    status: str
    summary: str = Field(
        default="",
        max_length=MAX_SUMMARY_LENGTH,
        description="事件摘要，最长 2000 字符",
    )
    source_refs: list[SourceRef] = Field(
        default_factory=list,
        max_length=MAX_SOURCE_REFS,
        description="引用来源，最多 20 条",
    )
    duration_ms: int | None = None


# ---- D 返回的公开事件 ----

class AgentEvent(BaseModel):
    """D 持久化并发布的公开事件 — 逐字段白名单控制。"""
    id: str
    run_id: str
    sequence_no: int
    agent: str
    event_type: str
    status: str
    summary: str
    source_refs: list[SourceRef]
    duration_ms: int | None = None
    created_at: str


# ---- Run 状态 ----

class AgentRunSummary(BaseModel):
    """GET /api/agent-runs/{run_id} 的公开响应。"""
    id: str
    thread_id: str
    mode: str
    status: str
    model: str | None = None
    model_calls: int = 0
    node_hops: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_cny: float = 0.0
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str


# ---- Retry ----

class RetryAgentRunResponse(BaseModel):
    run: AgentRunSummary
    event_url: str
