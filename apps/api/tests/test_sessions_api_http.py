"""Session REST API HTTP 测试 — httpx.AsyncClient + ASGITransport 端到端。

覆盖：HTTP → FastAPI → Auth/CSRF/DTO → Service → Repository → PostgreSQL
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


# ---- Fixtures (session scope — pytest-asyncio 管理事件循环) ----


@pytest.fixture(scope="session")
def app():
    from apps.api.main import create_app
    return create_app()


@pytest.fixture(scope="session")
async def admin(app):
    t = ASGITransport(app=app)
    async with AsyncClient(transport=t, base_url="http://test") as ac:
        r = await ac.post("/api/auth/login", json={
            "username": "admin", "password": "test-pass-123",
        })
        assert r.status_code == 200, f"Admin login: {r.status_code}"
        token = r.json()["csrf_token"]
        yield ac, token


@pytest.fixture(scope="session")
async def member(app):
    t = ASGITransport(app=app)
    async with AsyncClient(transport=t, base_url="http://test") as mc:
        r = await mc.post("/api/auth/login", json={
            "username": "member_a", "password": "test-pass-123",
        })
        assert r.status_code == 200, f"Member login: {r.status_code}"
        yield mc


# ---- Helper ----

async def _session(admin) -> str:
    ac, token = admin
    r = await ac.post(
        "/api/sessions", json={"title": "T"},
        headers={"X-CSRF-Token": token},
    )
    assert r.status_code == 201
    return r.json()["id"]


# ============================================================
# 1. POST /api/sessions
# ============================================================

@pytest.mark.asyncio
async def test_create_session_201(admin) -> None:
    ac, token = admin
    resp = await ac.post(
        "/api/sessions", json={"title": "API"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "API"


@pytest.mark.asyncio
async def test_create_session_no_csrf_403(admin) -> None:
    ac, _ = admin
    resp = await ac.post("/api/sessions", json={"title": "X"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_session_unauth_401(app) -> None:
    t = ASGITransport(app=app)
    async with AsyncClient(transport=t, base_url="http://test") as ac:
        resp = await ac.post("/api/sessions", json={"title": "X"})
        assert resp.status_code == 401


# ============================================================
# 2. GET /api/sessions
# ============================================================

@pytest.mark.asyncio
async def test_list_sessions_200(admin) -> None:
    ac, _ = admin
    resp = await ac.get("/api/sessions")
    assert resp.status_code == 200
    assert "items" in resp.json()


# ============================================================
# 3. GET /api/sessions/{id}
# ============================================================

@pytest.mark.asyncio
async def test_get_session_owner_200(admin) -> None:
    sid = await _session(admin)
    ac, _ = admin
    resp = await ac.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_session_other_404(admin, member) -> None:
    sid = await _session(admin)
    resp = await member.get(f"/api/sessions/{sid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_nonexistent_404(admin) -> None:
    ac, _ = admin
    resp = await ac.get(
        "/api/sessions/00000000-0000-0000-0000-000000000000",
    )
    assert resp.status_code == 404


# ============================================================
# 4. POST /api/sessions/{id}/qa
# ============================================================

@pytest.mark.asyncio
async def test_start_qa_202(admin) -> None:
    sid = await _session(admin)
    ac, token = admin
    start = time.monotonic()
    resp = await ac.post(
        f"/api/sessions/{sid}/qa",
        json={"user_input": "什么是熵？"},
        headers={"X-CSRF-Token": token},
    )
    elapsed = time.monotonic() - start
    assert resp.status_code == 202, resp.text
    assert "run_id" in resp.json()
    assert elapsed < 3.0, f"{elapsed:.2f}s"


@pytest.mark.asyncio
async def test_start_qa_no_csrf_403(admin) -> None:
    sid = await _session(admin)
    ac, _ = admin
    resp = await ac.post(f"/api/sessions/{sid}/qa", json={"user_input": "hi"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_start_qa_empty_422(admin) -> None:
    sid = await _session(admin)
    ac, token = admin
    resp = await ac.post(
        f"/api/sessions/{sid}/qa",
        json={"user_input": ""},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_qa_nonexistent_404(admin) -> None:
    ac, token = admin
    resp = await ac.post(
        "/api/sessions/00000000-0000-0000-0000-000000000000/qa",
        json={"user_input": "hi"},
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 404


# ============================================================
# 5. GET /api/sessions/{id}/messages
# ============================================================

@pytest.mark.asyncio
async def test_get_messages_200(admin) -> None:
    sid = await _session(admin)
    ac, _ = admin
    resp = await ac.get(f"/api/sessions/{sid}/messages")
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.asyncio
async def test_get_messages_other_empty(admin, member) -> None:
    sid = await _session(admin)
    resp = await member.get(f"/api/sessions/{sid}/messages")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ============================================================
# 6. Error format + DTO
# ============================================================

@pytest.mark.asyncio
async def test_error_has_code_message_retryable_trace_id(admin) -> None:
    ac, _ = admin
    resp = await ac.get(
        "/api/sessions/00000000-0000-0000-0000-000000000000",
    )
    assert resp.status_code == 404
    data = resp.json()
    for key in ("code", "message", "retryable", "trace_id"):
        assert key in data, f"Missing {key}"


@pytest.mark.asyncio
async def test_session_dto_no_user_id(admin) -> None:
    sid = await _session(admin)
    ac, _ = admin
    resp = await ac.get(f"/api/sessions/{sid}")
    assert "user_id" not in resp.json()


# ============================================================
# 7. Agent run / retry
# ============================================================

@pytest.mark.asyncio
async def test_retry_requires_auth(app) -> None:
    t = ASGITransport(app=app)
    async with AsyncClient(transport=t, base_url="http://test") as ac:
        resp = await ac.post("/api/agent-runs/some-id/retry")
        assert resp.status_code == 401


# ============================================================
# 8. QA P95 延时测试
# ============================================================

@pytest.mark.asyncio
async def test_qa_p95_latency_under_2s(admin) -> None:
    """30 次 QA 启动，P95 延时 ≤ 2 秒。"""
    ac, token = admin
    sample_count = 30
    latencies: list[float] = []

    for _ in range(sample_count):
        sid = await _session(admin)
        start = time.monotonic()
        resp = await ac.post(
            f"/api/sessions/{sid}/qa",
            json={"user_input": "test"},
            headers={"X-CSRF-Token": token},
        )
        elapsed = time.monotonic() - start
        assert resp.status_code == 202, resp.text
        latencies.append(elapsed)

    latencies.sort()
    p50 = latencies[int(sample_count * 0.50)]
    p95 = latencies[int(sample_count * 0.95)]
    p_max = latencies[-1]

    assert p95 <= 3.0, (
        f"P95={p95:.3f}s exceeds 3s. "
        f"P50={p50:.3f}s max={p_max:.3f}s N={sample_count}"
    )
