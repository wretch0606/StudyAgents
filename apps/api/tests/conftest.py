"""pytest fixtures for API tests."""

# ruff: noqa: I001  — import ordering is deliberate: APP_ENV must be set before apps.api imports

from __future__ import annotations

import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

# 必须在任何 apps.api 导入前设置，确保 Settings 以 app_env="test" 初始化
os.environ["APP_ENV"] = "test"

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# 确保项目根目录在 Python path 中
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.main import create_app  # noqa: E402


# ---- 测试环境 Engine 配置 ----

@pytest.fixture(scope="session", autouse=True)
async def _configure_test_engine():
    """测试环境 Engine 生命周期管理。

    session 开始前释放可能已存在的旧 engine（非 NullPool），
    session 结束后释放 engine 资源。
    """
    from apps.api.db.session import dispose_engine

    # 释放可能已存在的旧 engine
    await dispose_engine()

    yield

    # session 结束后清理
    await dispose_engine()


# ---- 通用客户端 fixtures ----

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
