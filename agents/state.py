"""
AgentState — LangGraph 状态图中流转的状态对象。

基于 contracts/agent-state.schema.json，字段分为三类：
- public:   可进入 SSE 事件和 API 响应
- private:  仅服务端可见，不暴露给学生
- strict:   仅 Agent 内部使用（答案/评分点），API 出口必须剥离

依赖: typing_extensions (Python <3.11) 或 typing (Python >=3.11)
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, TypedDict

# ── 检索过滤条件 ────────────────────────────────────


class RetrievalFilters(TypedDict, total=False):
    """对应 c/schemas.py 的 RetrievalFilters"""
    chapter_ids: list[str]
    question_types: Optional[list[str]]
    difficulty: Optional[int]
    exclude_chunk_ids: list[str]
    knowledge_point_ids: list[str]
    year: Optional[int]


# ── SourceRef（与 contracts/source-ref.schema.json 一致）────


class SourceRef(TypedDict):
    document_id: str          # UUID
    document_name: str        # "光学讲义.pdf"
    page_number: int          # ≥1
    question_no: Optional[str]
    chunk_id: str             # UUID
    excerpt: str              # ≤300 字
    page_image_url: Optional[str]
    score: float              # RRF 分数


# ── 知识条目 ─────────────────────────────────────────


class KnowledgeItem(TypedDict):
    fact: str
    source_ref_ids: list[str]  # 指向 SourceRef.document_id
    knowledge_point_ids: list[str]


# ── 公开事件摘要 ─────────────────────────────────────


class AgentEvent(TypedDict):
    id: str
    run_id: str
    sequence_no: int
    agent: Literal["coordinator", "knowledge", "questioner", "evaluator", "system"]
    event_type: Literal[
        "run.started", "agent.started", "agent.summary",
        "agent.completed", "run.waiting_user", "run.completed",
        "run.failed", "heartbeat"
    ]
    status: Literal["queued", "running", "waiting_user", "succeeded", "failed"]
    summary: str
    source_refs: list[SourceRef]
    duration_ms: float
    created_at: str  # ISO 8601


# ── 统一错误 ─────────────────────────────────────────


class ApiError(TypedDict):
    code: str
    message: str
    retryable: bool
    trace_id: str
    details: Optional[dict[str, Any]]


# ═══════════════════════════════════════════════════════
# AgentState — 核心状态对象
# ═══════════════════════════════════════════════════════


class AgentState(TypedDict, total=False):
    """
    字段边界:
    - public:  SSE 事件 / API 响应中可暴露
    - private: 仅服务端，D 必须在序列化时过滤
    - strict:  仅 Agent 内部节点间流转，绝对不能进入 API
    """

    # ── public ──
    run_id: str                     # UUID
    thread_id: str                  # UUID
    user_id: str                    # UUID
    mode: Literal["qa", "practice"]
    user_input: str
    filters: RetrievalFilters
    public_response: Optional[str]  # 最终公开输出
    model_calls: int                # 已用模型调用次数
    node_hops: int                  # 已跳节点数
    retry_count: int                # 当前步骤重试次数
    error: Optional[ApiError]

    # ── private ──
    evidence: list[SourceRef]       # 可能含 staff_only 块
    knowledge: list[KnowledgeItem]

    # ── strict ──
    user_answer: Optional[str]      # 用户提交的答案原文
    # question_private / grade_private 由 Day 3-4 补充
