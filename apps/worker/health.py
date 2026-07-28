"""Worker 健康状态 — 命令行 `--check` 或内部检查使用。"""

from __future__ import annotations

from enum import Enum


class WorkerStatus(str, Enum):
    starting = "starting"
    ready = "ready"
    degraded = "degraded"
    stopping = "stopping"


class HealthReport:
    """Worker 健康检查报告。"""

    def __init__(self) -> None:
        self.status: WorkerStatus = WorkerStatus.starting
        self.checks: dict[str, bool] = {}
        self.errors: dict[str, str] = {}

    def add_check(self, name: str, ok: bool, error: str = "") -> None:
        self.checks[name] = ok
        if not ok:
            self.errors[name] = error

    def all_ok(self) -> bool:
        return all(self.checks.values()) if self.checks else False

    def summary(self) -> str:
        lines = [f"Worker status: {self.status.value}"]
        for name, ok in self.checks.items():
            marker = "OK" if ok else "FAIL"
            err = f" ({self.errors[name]})" if not ok and name in self.errors else ""
            lines.append(f"  [{marker}] {name}{err}")
        return "\n".join(lines)
