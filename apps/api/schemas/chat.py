"""Chat REST API 公开 DTO — 会话、消息和问答请求/响应。

白名单控制：禁止 internal AgentState、private 字段和思维链。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---- Session ----

class CreateSessionRequest(BaseModel):
    """POST /api/sessions 请求体。"""
    title: str | None = None
    thread_id: str | None = None  # 可选；不提供则自动生成


class SessionResponse(BaseModel):
    """会话公开 DTO。"""
    id: str
    title: str | None = None
    thread_id: str
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    """GET /api/sessions 分页响应。"""
    items: list[SessionResponse]
    total: int


# ---- QA ----

class StartQaRequest(BaseModel):
    """POST /api/sessions/{id}/qa 请求体。"""
    user_input: str = Field(min_length=1, max_length=10000)
    mode: str = "qa"  # "qa" | "practice"


class StartQaResponse(BaseModel):
    """QA 启动响应 — 立即返回 run_id。"""
    run_id: str
    thread_id: str
    trace_id: str


# ---- Message ----

class MessageResponse(BaseModel):
    """消息公开 DTO。"""
    model_config = ConfigDict(extra="forbid")

    id: str
    role: str  # "user" | "assistant"
    content: str
    run_id: str | None = None
    sequence_no: int
    created_at: str


class MessageListResponse(BaseModel):
    """GET /api/sessions/{id}/messages 响应。"""
    items: list[MessageResponse]
