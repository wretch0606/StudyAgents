"""Session REST API 测试 — 创建/列出/查询会话、发起 QA、消息历史、属主隔离。

使用 httpx.AsyncClient + ASGITransport（兼容 async SQLAlchemy）。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


# ---- Fixtures ----


@pytest.fixture(scope="module")
def test_app():
    """创建测试 app + 初始化 AgentRunnerService。"""
    from apps.api.main import create_app
    return create_app()


@pytest.fixture(scope="module")
async def shared_client(test_app):
    """模块级共享 AsyncClient（避免重复登录触发限速）。"""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="module")
async def admin_token(shared_client: AsyncClient):
    """模块级 admin 登录 token。"""
    resp = await shared_client.post("/api/auth/login", json={
        "username": "admin", "password": "test-pass-123",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text[:200]}"
    return resp.json()["csrf_token"]


@pytest.fixture
async def client(shared_client: AsyncClient):
    """每个测试独立的 client（共享底层 transport）。"""
    yield shared_client


async def _create_session(client: AsyncClient, token: str, title="Test") -> str:
    resp = await client.post(
        "/api/sessions",
        json={"title": title},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 201, f"Create session failed: {resp.text}"
    return resp.json()["id"]


# ============================================================
# 1. 创建会话
# ============================================================

@pytest.mark.asyncio
async def test_create_session_success(
    client: AsyncClient, admin_token: str,
) -> None:
    resp = await client.post(
        "/api/sessions",
        json={"title": "Test Session"},
        headers={"X-CSRF-Token": admin_token},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "Test Session"
    assert "id" in data
    assert "thread_id" in data


@pytest.mark.asyncio
async def test_create_session_no_csrf_rejected(
    client: AsyncClient,
) -> None:
    resp = await client.post("/api/sessions", json={"title": "Bad"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_session_unauthenticated_rejected(
    client: AsyncClient,
) -> None:
    resp = await client.post("/api/sessions", json={"title": "NoAuth"})
    assert resp.status_code == 401


# ============================================================
# 2. 列出会话
# ============================================================

@pytest.mark.asyncio
async def test_list_sessions_returns_own(
    client: AsyncClient, admin_token: str,
) -> None:
    await _create_session(client, admin_token, "My Session")
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_list_sessions_unauthenticated_rejected(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/sessions")
    assert resp.status_code == 401


# ============================================================
# 3. 查询会话详情
# ============================================================

@pytest.mark.asyncio
async def test_get_session_owner_success(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "My Detail")
    resp = await client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "My Detail"


@pytest.mark.asyncio
async def test_get_session_other_user_not_found(
    client: AsyncClient, admin_token: str, test_app,
) -> None:
    sid = await _create_session(client, admin_token, "Admin Only")

    t2 = ASGITransport(app=test_app)
    async with AsyncClient(transport=t2, base_url="http://test") as mc:
        r = await mc.post("/api/auth/login", json={
            "username": "member_a", "password": "test-pass-123",
        })
        assert r.status_code == 200
        r = await mc.get(f"/api/sessions/{sid}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_session_nonexistent_404(
    client: AsyncClient,
) -> None:
    resp = await client.get(
        "/api/sessions/00000000-0000-0000-0000-000000000000",
    )
    assert resp.status_code == 404


# ============================================================
# 4. 发起 QA
# ============================================================

@pytest.mark.asyncio
async def test_start_qa_returns_run_id_immediately(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "QA Session")

    start = time.monotonic()
    resp = await client.post(
        f"/api/sessions/{sid}/qa",
        json={"user_input": "什么是熵？"},
        headers={"X-CSRF-Token": admin_token},
    )
    elapsed = time.monotonic() - start

    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert "run_id" in data
    assert "thread_id" in data
    assert "trace_id" in data
    assert data["trace_id"].startswith("trace-")
    assert elapsed < 2.0, f"QA start took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_start_qa_nonexistent_session_404(
    client: AsyncClient, admin_token: str,
) -> None:
    resp = await client.post(
        "/api/sessions/00000000-0000-0000-0000-000000000000/qa",
        json={"user_input": "hello"},
        headers={"X-CSRF-Token": admin_token},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_start_qa_other_user_session_404(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "Admin QA")

    # Login as member in a fresh client
    transport = ASGITransport(app=client._transport.app)
    async with AsyncClient(transport=transport, base_url="http://test") as member_client:
        resp = await member_client.post("/api/auth/login", json={
            "username": "member_a", "password": "test-pass-123",
        })
        assert resp.status_code == 200
        member_token = resp.json()["csrf_token"]
        resp = await member_client.post(
            f"/api/sessions/{sid}/qa",
            json={"user_input": "hello"},
            headers={"X-CSRF-Token": member_token},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_start_qa_no_csrf_rejected(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "CSRF Test")
    resp = await client.post(
        f"/api/sessions/{sid}/qa", json={"user_input": "hello"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_start_qa_empty_input_rejected(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "Validate")
    resp = await client.post(
        f"/api/sessions/{sid}/qa",
        json={"user_input": ""},
        headers={"X-CSRF-Token": admin_token},
    )
    assert resp.status_code == 422


# ============================================================
# 5. 消息历史
# ============================================================

@pytest.mark.asyncio
async def test_get_messages_history(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "Message Test")
    resp = await client.get(f"/api/sessions/{sid}/messages")
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_get_messages_other_user_sees_empty(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "Admin Msg")

    transport = ASGITransport(app=client._transport.app)
    async with AsyncClient(transport=transport, base_url="http://test") as member_client:
        resp = await member_client.post("/api/auth/login", json={
            "username": "member_a", "password": "test-pass-123",
        })
        assert resp.status_code == 200
        resp = await member_client.get(f"/api/sessions/{sid}/messages")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_get_messages_unauthenticated_rejected(
    client: AsyncClient,
) -> None:
    resp = await client.get(
        "/api/sessions/00000000-0000-0000-0000-000000000000/messages",
    )
    assert resp.status_code == 401


# ============================================================
# 6. 错误响应格式
# ============================================================

@pytest.mark.asyncio
async def test_error_response_format(
    client: AsyncClient,
) -> None:
    resp = await client.get("/api/sessions/nonexistent-id-12345")
    assert resp.status_code == 404
    data = resp.json()
    assert "code" in data
    assert "message" in data
    assert "retryable" in data
    assert data["retryable"] is False
    assert "trace_id" in data


# ============================================================
# 7. 公开 DTO 防泄露
# ============================================================

@pytest.mark.asyncio
async def test_session_response_no_private_fields(
    client: AsyncClient, admin_token: str,
) -> None:
    sid = await _create_session(client, admin_token, "No Leak")
    resp = await client.get(f"/api/sessions/{sid}")
    data = resp.json()
    allowed = {"id", "title", "thread_id", "created_at", "updated_at"}
    assert set(data.keys()) == allowed
    assert "user_id" not in data


def test_message_response_no_private_fields() -> None:
    from apps.api.schemas.chat import MessageResponse
    fields = set(MessageResponse.model_fields.keys())
    allowed = {"id", "role", "content", "run_id", "sequence_no", "created_at"}
    assert fields == allowed


# ============================================================
# 8. 重试 — 属主隔离
# ============================================================

@pytest.mark.asyncio
async def test_retry_run_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/agent-runs/some-id/retry")
    assert resp.status_code == 401
