"""提供 trace_id 的 FastAPI 依赖项。"""

from __future__ import annotations

from apps.api.middleware.trace import get_trace_id


def trace_id_dependency() -> str:
    """FastAPI Depends 可注入的 trace_id 获取器。"""
    return get_trace_id()
