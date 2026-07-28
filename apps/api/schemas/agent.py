"""Agent 运行时公开 DTO — 仅包含允许对外暴露的字段。

白名单过滤：禁止 question_private / grade_private / Prompt / 思维链。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---- C 提交的事件草稿 ----

class AgentEventDraft(BaseModel):
    """C 生成的事件草稿 — 通过 AgentEventSink.emit() 提交。"""
    agent: str
    event_type: str
    status: str
    summary: str
    source_refs: list[dict] = Field(default_factory=list)
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
    source_refs: list[dict]
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
