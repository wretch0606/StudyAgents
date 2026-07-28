"""trace_id 中间件与错误处理测试。"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import create_app  # noqa: E402
from apps.api.middleware.trace import TRACE_HEADER  # noqa: E402
from apps.api.schemas.error import ApiError  # noqa: E402


def _build_test_app() -> FastAPI:
    """构建带测试路由的独立 app 实例。"""
    app = create_app()

    @app.get("/__test__/ping")
    async def _ping() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/__test__/api-error")
    async def _api_error() -> None:
        raise ApiError("TEST_ERROR", "something went wrong", status_code=422, retryable=False)

    @app.get("/__test__/unhandled")
    async def _unhandled() -> None:
        raise RuntimeError("unexpected internal fault")

    return app


# ---- 测试 ----
def test_trace_id_in_response_header() -> None:
    """正常请求应返回 X-Trace-Id 响应头。"""
    with TestClient(_build_test_app()) as client:
        response = client.get("/__test__/ping")
    assert response.status_code == 200
    assert TRACE_HEADER in response.headers
    assert len(response.headers[TRACE_HEADER]) == 32


def test_passthrough_trace_id() -> None:
    """传入 X-Trace-Id 请求头时响应应透传同一 ID。"""
    custom_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    with TestClient(_build_test_app()) as client:
        response = client.get("/__test__/ping", headers={TRACE_HEADER: custom_id})
    assert response.headers[TRACE_HEADER] == custom_id


def test_api_error_includes_trace_id() -> None:
    """ApiError 错误响应必须包含 trace_id。"""
    with TestClient(_build_test_app()) as client:
        response = client.get("/__test__/api-error")
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "TEST_ERROR"
    assert data["retryable"] is False
    assert "trace_id" in data
    assert len(data["trace_id"]) > 0


def test_unhandled_error_no_stack_trace() -> None:
    """未处理异常不应向客户端返回堆栈信息。"""
    with TestClient(_build_test_app()) as client:
        response = client.get("/__test__/unhandled")
    assert response.status_code == 500
    data = response.json()
    assert data["code"] == "INTERNAL_ERROR"
    assert "trace_id" in data
    assert len(data["trace_id"]) > 0
    assert "RuntimeError" not in str(data)
    assert "unexpected internal fault" not in str(data)
    assert "traceback" not in str(data).lower()


def test_trace_id_unique_per_request() -> None:
    """每个请求应有不同的 trace_id（未传入时）。"""
    ids: set[str] = set()
    with TestClient(_build_test_app()) as client:
        for _ in range(5):
            response = client.get("/__test__/ping")
            ids.add(response.headers[TRACE_HEADER])
    assert len(ids) == 5
