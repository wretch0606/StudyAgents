"""pytest fixtures for API tests."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# 确保项目根目录在 Python path 中
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.main import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """同步 TestClient，使用工厂创建独立 app。"""
    return TestClient(create_app())


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient]:
    """异步 httpx 客户端，直接走 ASGI transport。"""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
