"""健康检查端点测试。"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import create_app  # noqa: E402


def test_live_returns_ok() -> None:
    """GET /api/health/live 应返回 200 和 status ok，不依赖数据库。"""
    with TestClient(create_app()) as client:
        response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_returns_ok_or_degraded() -> None:
    """GET /api/health/ready 应返回 trace_id 和 database 状态。

    数据库不可用时返回 503 + degraded，不崩溃。
    """
    with TestClient(create_app()) as client:
        response = client.get("/api/health/ready")
    data = response.json()
    assert "trace_id" in data
    assert len(data["trace_id"]) > 0
    assert "status" in data
    assert data["status"] in ("ok", "degraded")
    assert "database" in data
    assert "connected" in data["database"]
