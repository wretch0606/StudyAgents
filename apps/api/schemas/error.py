"""统一错误响应模型 — 对齐 contracts/error.schema.json。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiErrorResponse(BaseModel):
    """所有 API 错误的统一响应格式。

    前端根据 `retryable` 决定是否显示重试按钮，不根据 message 文本解析。
    """

    code: str
    message: str
    retryable: bool
    trace_id: str
    details: Any = None


class ApiError(Exception):
    """应用级异常，由全局 exception handler 捕获并转为 ApiErrorResponse。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.details = details
