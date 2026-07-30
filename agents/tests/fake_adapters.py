"""
Fake 适配器 — 用于 Day 6 弹性测试的故障注入工具。

提供:
  - FakeModelGateway:  模拟正常/超时/429/5xx/无效JSON/低置信度
  - FakeRetriever:     模拟检索结果
  - FakeEventSink:     记录事件，用于隐私扫描
  - FakeCheckpointer:  模拟 LangGraph checkpoint 存储

用法:
  from agents.tests.fake_adapters import FakeModelGateway, FaultConfig
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


# ═══════════════════════════════════════════════════════
# 故障配置
# ═══════════════════════════════════════════════════════


@dataclass
class FaultConfig:
    """可组合的故障注入配置"""

    # 模拟超时（秒），None 表示不超时
    timeout_seconds: float | None = None

    # 模拟 HTTP 错误：None / 429 / 500 / 502 / 503
    http_error: int | None = None

    # 模拟无效 JSON（返回非 JSON 文本）
    invalid_json: bool = False

    # 模拟错误 Schema（返回 Schema 不匹配的 JSON）
    wrong_schema: bool = False

    # 第 N 次调用才触发故障（0 = 每次都触发）
    trigger_on_call: int = 0

    # 低置信度（< 0.8 触发降级）
    low_confidence: bool = False

    # 模拟空检索结果
    empty_retrieval: bool = False

    # 模拟错误引用（引用了不存在的 chunk_id）
    bad_citation: bool = False

    # 模拟评分超上限
    score_overflow: bool = False


# ═══════════════════════════════════════════════════════
# FakeModelGateway
# ═══════════════════════════════════════════════════════


class FakeModelGateway:
    """
    模拟 D 的 ModelGateway，支持故障注入。

    正常行为: 返回符合 output_schema 的合理输出。
    故障行为: 根据 FaultConfig 注入超时/429/5xx/无效JSON/错误Schema。

    用法:
        # 正常调用
        gw = FakeModelGateway()
        result = await gw.invoke_structured(...)

        # 注入超时
        gw = FakeModelGateway(fault=FaultConfig(timeout_seconds=30.0))

        # 第 3 次调用返回 429
        gw = FakeModelGateway(fault=FaultConfig(http_error=429, trigger_on_call=3))
    """

    # ── 默认输出模板 ──
    DEFAULT_OUTPUTS: dict[str, dict] = {
        "CoordinatorDecision": {
            "intent": "qa_ask",
            "normalized_query": "测试查询",
            "filters": {"chapter_ids": [], "question_types": None, "difficulty": None},
            "next_node": "knowledge",
            "public_summary": "协调 Agent 识别为自由问答模式",
        },
        "KnowledgeResult": {
            "sufficient": True,
            "reason": "sufficient",
            "knowledge_items": [
                {
                    "fact": "数据库管理系统是用于管理数据的软件系统。",
                    "source_ref_ids": ["chunk-test-001"],
                    "knowledge_point_ids": [],
                }
            ],
            "selected_source_ref_ids": ["chunk-test-001"],
            "requires_vision": False,
            "public_summary": "找到 1 条可引用证据，判断证据充足",
        },
        "QAAnswer": {
            "answer": "数据库管理系统（DBMS）是用于管理数据的软件系统[test.pdf 第1页]。",
            "citations": [],
            "source_ref_ids": ["chunk-test-001"],
            "confidence_note": "",
            "public_summary": "回答已完成引用核验",
        },
        "GeneratedQuestionPrivate": {
            "question_id": "q-test-001",
            "source_kind": "past_exam",
            "question_type": "choice",
            "difficulty": 2,
            "stem": "数据库管理系统的核心目标是什么？",
            "options": [
                {"id": "A", "text": "管理数据"},
                {"id": "B", "text": "管理硬件"},
                {"id": "C", "text": "管理网络"},
                {"id": "D", "text": "管理系统"},
            ],
            "knowledge_point_ids": [],
            "source_refs": [],
            "private": {
                "expected_answer": "A",
                "rubric": [
                    {
                        "id": "R1",
                        "description": "选择正确选项",
                        "max_score": 5,
                        "source_ref_ids": ["chunk-test-001"],
                    }
                ],
            },
            "confidence": 0.95,
            "public_summary": "出题完成",
        },
        "GradeResultPrivate": {
            "score": 8,
            "max_score": 10,
            "step_scores": [
                {
                    "rubric_item_id": "R1",
                    "status": "met",
                    "score": 5,
                    "feedback": "计算正确",
                },
                {
                    "rubric_item_id": "R2",
                    "status": "partial",
                    "score": 3,
                    "feedback": "推理过程部分正确",
                },
            ],
            "explanation": "整体正确，部分步骤可以更完整。",
            "source_ref_ids": ["chunk-test-001"],
            "confidence": 0.85,
            "review_required": False,
            "public_summary": "评分完成",
        },
    }

    # D 的重试配置
    MAX_RETRIES = 2  # D 的 ModelGateway 最多重试 2 次

    def __init__(
        self,
        fault: FaultConfig | None = None,
        outputs: dict[str, dict] | None = None,
    ):
        self.fault = fault or FaultConfig()
        self.outputs = {**self.DEFAULT_OUTPUTS, **(outputs or {})}
        self.call_count = 0
        self.call_log: list[dict] = []  # 记录所有调用，用于测试断言
        self._internal_retries = 0  # 本次请求的内部重试次数

    def _should_inject_fault(self) -> bool:
        """判断当前调用是否应注入故障"""
        if self.fault.trigger_on_call == 0:
            return True
        return self.call_count == self.fault.trigger_on_call

    def _schema_name(self, output_schema: type) -> str:
        """从类型中提取 Schema 名称"""
        return output_schema.__name__ if hasattr(output_schema, "__name__") else str(output_schema)

    async def invoke_structured(
        self,
        *,
        run_id: str = "",
        trace_id: str = "trace-test",
        agent: str = "test",
        prompt_version: str = "v1",
        messages: list | None = None,
        output_schema: type | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SimpleNamespace:
        """
        模拟 ModelGateway.invoke_structured()。

        模拟 D 的行为：
          1. 内部重试最多 2 次（对 timeout/429/5xx/无效 JSON）
          2. 重试耗尽后抛 ModelGatewayError（由 D 的 AgentRunner 层捕获）
          3. 正常情况返回与 output_schema 匹配的输出
        """
        self.call_count += 1
        self._internal_retries = 0
        call_start = time.monotonic()

        schema_name = self._schema_name(output_schema) if output_schema else "unknown"
        self.call_log.append(
            {
                "call_no": self.call_count,
                "agent": agent,
                "schema": schema_name,
                "prompt_version": prompt_version,
                "fault_injected": False,
                "fault_type": None,
                "internal_retries": 0,
            }
        )

        # ── 内部重试循环（模拟 D 的重试逻辑）──
        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):  # 初始 + 2 次重试 = 最多 3 次
            if attempt > 0:
                self._internal_retries += 1
                # 指数退避：1s, 2s
                await asyncio.sleep(min(2 ** (attempt - 1), 3.0))

            try:
                return await self._do_invoke(
                    schema_name=schema_name,
                    output_schema=output_schema,
                    call_start=call_start,
                    attempt=attempt + 1,
                )
            except (asyncio.TimeoutError, ModelGatewayError) as e:
                last_error = e
                # 不可重试的错误直接抛
                if isinstance(e, ModelGatewayError) and not e.retryable:
                    self.call_log[-1]["fault_type"] = f"http_{e.status_code}"
                    self.call_log[-1]["fault_injected"] = True
                    raise

        # 重试耗尽
        self.call_log[-1]["internal_retries"] = self._internal_retries
        self.call_log[-1]["fault_injected"] = True
        if isinstance(last_error, asyncio.TimeoutError):
            self.call_log[-1]["fault_type"] = "timeout_exhausted"
            raise ModelGatewayError(
                status_code=504,
                message=f"模型调用超时，已重试 {self.MAX_RETRIES} 次",
                retryable=False,
            )
        raise last_error  # type: ignore[misc]

    async def _do_invoke(
        self,
        schema_name: str,
        output_schema: type | None,
        call_start: float,
        attempt: int,
    ) -> SimpleNamespace:
        """执行单次模型调用（可能被重试包装）"""

        # ── 故障注入 ──
        if self._should_inject_fault():
            # 模拟超时
            if self.fault.timeout_seconds is not None:
                await asyncio.sleep(min(self.fault.timeout_seconds, 2.0))
                raise asyncio.TimeoutError(
                    f"模型调用超时（{self.fault.timeout_seconds}s）"
                )

            # 模拟 HTTP 错误
            if self.fault.http_error is not None:
                raise ModelGatewayError(
                    status_code=self.fault.http_error,
                    message=f"HTTP {self.fault.http_error}",
                    retryable=self.fault.http_error in (429, 500, 502, 503),
                )

            # 模拟无效 JSON
            if self.fault.invalid_json:
                raise ModelGatewayError(
                    status_code=200,
                    message="Invalid JSON response from model",
                    retryable=True,
                )

            # 模拟错误 Schema
            if self.fault.wrong_schema:
                return SimpleNamespace(
                    output=SimpleNamespace(
                        unexpected_field="wrong_structure"
                    ),
                    provider="fake",
                    model="fake-model-v1",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                    estimated_cost_cny=0.001,
                )

        # ── 正常输出 ──
        template = self.outputs.get(schema_name, {})
        if output_schema and template:
            data = dict(template)

            # 低置信度模式
            if self.fault.low_confidence and "confidence" in data:
                data["confidence"] = 0.5

            # 错误引用模式
            if self.fault.bad_citation and "source_ref_ids" in data:
                data["source_ref_ids"] = ["chunk-nonexistent"]

            # 评分超上限
            if self.fault.score_overflow and schema_name == "GradeResultPrivate":
                data.update({
                    "score": 100,
                    "max_score": 10,
                    "step_scores": [
                        {
                            "rubric_item_id": "R1",
                            "status": "met",
                            "score": 100,
                            "feedback": "超上限评分",
                        }
                    ],
                })

            try:
                output = output_schema(**data)
            except Exception:
                output = SimpleNamespace(**data) if isinstance(data, dict) else data

            latency = int((time.monotonic() - call_start) * 1000)
            return SimpleNamespace(
                output=output,
                provider="fake",
                model="fake-model-v1",
                input_tokens=50,
                output_tokens=100,
                latency_ms=latency,
                estimated_cost_cny=0.002,
            )

        # 无模板时返回空的 SimpleNamespace
        return SimpleNamespace(
            output=SimpleNamespace(),
            provider="fake",
            model="fake-model-v1",
            input_tokens=10,
            output_tokens=10,
            latency_ms=50,
            estimated_cost_cny=0.001,
        )


# ═══════════════════════════════════════════════════════
# ModelGatewayError
# ═══════════════════════════════════════════════════════


class ModelGatewayError(Exception):
    """模拟 D 的 ModelGateway 异常"""

    def __init__(self, status_code: int, message: str, retryable: bool = True):
        self.status_code = status_code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


# ═══════════════════════════════════════════════════════
# FakeRetriever
# ═══════════════════════════════════════════════════════


@dataclass
class FakeSourceRef:
    document_id: str
    document_name: str
    page_number: int
    question_no: str | None
    chunk_id: str
    excerpt: str
    page_image_url: str | None = None
    score: float = 0.85

    def get(self, key: str, default=None):
        """兼容 dict-like 访问（_format_refs 使用 .get()）"""
        mapping = {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page_number": self.page_number,
            "question_no": self.question_no,
            "chunk_id": self.chunk_id,
            "excerpt": self.excerpt,
            "page_image_url": self.page_image_url,
            "score": self.score,
        }
        return mapping.get(key, default)

    def __getitem__(self, key: str):
        """支持 [] 访问"""
        result = self.get(key)
        if result is None and key not in {
            "document_id", "document_name", "page_number", "chunk_id",
            "excerpt", "score", "question_no", "page_image_url",
        }:
            raise KeyError(key)
        return result


@dataclass
class FakeRetrievalResult:
    source_refs: list[FakeSourceRef]


class FakeRetriever:
    """
    模拟 B 的 HybridRetriever。

    支持配置返回的检索结果数量和内容。
    """

    def __init__(
        self,
        refs: list[FakeSourceRef] | None = None,
        empty: bool = False,
    ):
        if empty:
            self._refs = []
        elif refs:
            self._refs = refs
        else:
            # 默认返回 3 条有效证据
            self._refs = [
                FakeSourceRef(
                    document_id="doc-test-001",
                    document_name="digital-lecture-intro.pdf",
                    page_number=1,
                    question_no=None,
                    chunk_id="chunk-test-001",
                    excerpt="数据库管理系统（DBMS）是用于管理数据的软件系统。",
                    score=0.95,
                ),
                FakeSourceRef(
                    document_id="doc-test-001",
                    document_name="digital-lecture-intro.pdf",
                    page_number=2,
                    question_no=None,
                    chunk_id="chunk-test-002",
                    excerpt="数据抽象包含三个层次：物理层、逻辑层和视图层。",
                    score=0.88,
                ),
                FakeSourceRef(
                    document_id="doc-test-001",
                    document_name="digital-lecture-intro.pdf",
                    page_number=3,
                    question_no=None,
                    chunk_id="chunk-test-003",
                    excerpt="关系数据模型使用表（关系）来组织数据。",
                    score=0.82,
                ),
            ]

    async def retrieve(self, query: str = "", filters: Any = None, user_role: str = "member") -> FakeRetrievalResult:
        return FakeRetrievalResult(source_refs=self._refs)


# ═══════════════════════════════════════════════════════
# FakeEventSink
# ═══════════════════════════════════════════════════════


class FakeEventSink:
    """
    模拟 D 的 AgentEventSink，记录所有事件供隐私扫描和断言。

    用法:
        sink = FakeEventSink()
        await sink.emit(run_id="r1", event=draft, db_session=None)
        assert not sink.has_private_field("expected_answer")
    """

    def __init__(self):
        self.events: list[dict] = []

    async def emit(self, run_id: str, event: Any, db_session: Any = None) -> None:
        """记录事件到内部列表"""
        record = {
            "run_id": run_id,
            "agent": getattr(event, "agent", "unknown"),
            "event_type": getattr(event, "event_type", "unknown"),
            "status": getattr(event, "status", "unknown"),
            "summary": getattr(event, "summary", ""),
            "source_refs": getattr(event, "source_refs", []),
        }
        self.events.append(record)

    def has_private_field(self, field_name: str) -> bool:
        """检查任何事件中是否包含指定私有字段"""
        for event in self.events:
            if field_name in str(event):
                return True
        return False

    def all_events_public(self, forbidden_fields: list[str]) -> list[str]:
        """
        扫描所有事件，返回泄露的字段列表。

        Returns:
            空列表表示无泄露。
        """
        leaked = []
        for event in self.events:
            event_str = json.dumps(event, ensure_ascii=False, default=str)
            for field in forbidden_fields:
                if field in event_str and field not in leaked:
                    leaked.append(field)
        return leaked

    def clear(self):
        self.events = []


# ═══════════════════════════════════════════════════════
# FakeCheckpointer
# ═══════════════════════════════════════════════════════


class FakeCheckpointer:
    """
    模拟 LangGraph 的 checkpointer（用于状态恢复测试）。

    支持:
      - 保存 checkpoint（模拟写入）
      - 恢复 checkpoint（模拟读取）
      - 模拟崩溃恢复
    """

    def __init__(self):
        self._store: dict[str, dict] = {}

    def put(self, config: dict, checkpoint: dict, metadata: dict | None = None) -> None:
        """保存 checkpoint"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        self._store[thread_id] = {
            "checkpoint": checkpoint,
            "metadata": metadata or {},
        }

    def get(self, config: dict) -> dict | None:
        """恢复 checkpoint"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        return self._store.get(thread_id)

    def list(self, config: dict | None = None) -> list[dict]:
        """列出所有 checkpoint"""
        return [
            {"config": {"configurable": {"thread_id": tid}}, "checkpoint": data["checkpoint"]}
            for tid, data in self._store.items()
        ]

    def delete_thread(self, thread_id: str) -> None:
        """删除指定线程的 checkpoint"""
        self._store.pop(thread_id, None)
