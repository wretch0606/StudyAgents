"""B Pipeline 适配接口 — 定义任务处理器的抽象边界。

D 负责接口定义 + 调度框架；B 负责具体处理逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# ---- 错误类型 ----

class HandlerNotConfiguredError(Exception):
    """对应任务类型未注册处理器。"""

    def __init__(self, task_type: str) -> None:
        super().__init__(f"No handler configured for task type: {task_type}")
        self.task_type = task_type


class UnsupportedTaskTypeError(Exception):
    """任务类型不在已知范围内。"""

    def __init__(self, task_type: str) -> None:
        super().__init__(f"Unsupported task type: {task_type}")
        self.task_type = task_type


# ---- 任务与结果 ----

@dataclass
class WorkerTask:
    """Worker 任务单元。

    可扩展字段以适配实际导入任务（Issue #11）。
    """

    task_id: str
    task_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_context: dict[str, str] = field(default_factory=dict)


@dataclass
class WorkerResult:
    """任务执行结果。"""

    task_id: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    retryable: bool | None = None


# ---- 处理器接口 ----

class PipelineHandler(Protocol):
    """B Pipeline 处理器协议。

    B 成员的每个任务类型实现此接口，通过 HandlerRegistry 注册。
    """

    async def handle(self, task: WorkerTask) -> WorkerResult:
        """处理一个 Worker 任务。"""
        ...


# ---- 处理器注册表 ----

class HandlerRegistry:
    """按任务类型注册 PipelineHandler。

    用法:
        registry = HandlerRegistry()
        registry.register("ingestion", my_ingestion_handler)
        handler = registry.get("ingestion")
    """

    def __init__(self) -> None:
        self._handlers: dict[str, PipelineHandler] = {}

    def register(self, task_type: str, handler: PipelineHandler) -> None:
        """注册处理器（B 成员调用）。"""
        self._handlers[task_type] = handler

    def get(self, task_type: str) -> PipelineHandler | None:
        """获取处理器；未注册返回 None。"""
        return self._handlers.get(task_type)

    def list_registered(self) -> list[str]:
        """列出已注册的任务类型。"""
        return list(self._handlers.keys())
