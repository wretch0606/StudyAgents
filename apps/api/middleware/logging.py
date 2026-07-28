"""JSON 结构化日志配置。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from .trace import get_trace_id


class JsonFormatter(logging.Formatter):
    """将日志格式化为单行 JSON，包含 trace_id、时间戳和基本信息。"""

    def format(self, record: logging.LogRecord) -> str:
        trace_id = get_trace_id()
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id or "",
            "module": record.name,
            "event": record.msg % record.args if record.args else record.msg,
        }
        if record.exc_info and record.exc_info[1]:
            payload["error"] = str(record.exc_info[1])

        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """配置应用根 logger 使用 JSON 格式输出到 stdout。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
