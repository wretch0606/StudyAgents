"""管理接口 HTTP 权限集成测试 — 验证完整请求链路。

覆盖:
  - 普通成员 → GET /api/admin/health → 403
  - 管理员 → GET /api/admin/health → 200
  - 未登录 → GET /api/admin/health → 401
  - 错误响应符合公共错误契约 (code, message, retryable, trace_id)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.services.auth import hash_password  # noqa: E402

# ---- 内存存储 ----
_users_db: dict[str, dict] = {}
_sessions_db: dict[str, dict] = {}


def _seed() -> None:
    _users_db.clear()
    _sessions_db.clear()
    import apps.api.services.auth as auth_svc
    auth_svc._rate_store.clear()
    import apps.api.dependencies.auth as auth_dep
    auth_dep._csrf_store.clear()

    _users_db["admin"] = {
        "id": "u-admin-001", "username": "admin", "display_name": "Admin",
        "role": "admin", "password_hash": hash_password("admin123"), "is_active": True,
    }
    _users_db["member1"] = {
        "id": "u-memb-001", "username": "member1", "display_name": "Member One",
        "role": "member", "password_hash": hash_password("memb123"), "is_active": True,
    }


@pytest.fixture
def client() -> TestClient:
    from apps.api.db.session import get_session
    from apps.api.middleware.trace import TraceMiddleware, get_trace_id
    from apps.api.routers.admin import router as admin_router
    from apps.api.routers.auth import router as auth_router
    from apps.api.schemas.error import ApiError, ApiErrorResponse

    app = FastAPI()
    app.add_middleware(TraceMiddleware)
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    # 覆盖 DB session — 直接用函数引用
    class _FakeSession:
        def __init__(self):
            self.committed = False
        def add(self, obj): pass
        async def flush(self): pass
        async def commit(self): self.committed = True
        async def rollback(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    async def _override_get_session():
        yield _FakeSession()

    app.dependency_overrides[get_session] = _override_get_session

    @app.exception_handler(ApiError)
    async def _h(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiErrorResponse(
                code=exc.code, message=exc.message, retryable=exc.retryable,
                trace_id=get_trace_id(), details=exc.details,
            ).model_dump(),
        )

    # monkey-patch repositories
    from types import SimpleNamespace

    import apps.api.repositories.auth as repo

    _originals = {
        "find_user_by_username": repo.find_user_by_username,
        "create_auth_session": repo.create_auth_session,
        "find_session_by_token_hash": repo.find_session_by_token_hash,
        "revoke_session": repo.revoke_session,
        "touch_session": repo.touch_session,
        "find_user_by_id": repo.find_user_by_id,
    }

    async def _find_user(session, username):
        u = _users_db.get(username)
        if not u:
            return None
        return SimpleNamespace(
            id=u["id"], username=u["username"], display_name=u["display_name"],
            role=u["role"], password_hash=u["password_hash"], is_active=u["is_active"],
        )

    async def _create_session(session, user_id, th, expires_at, client_info=None):
        matched = next((u for u in _users_db.values() if u["id"] == user_id), None)
        _sessions_db[th] = {
            "user_id": user_id,
            "username": matched["username"] if matched else "",
            "role": matched["role"] if matched else "member",
            "revoked": False,
        }

    async def _find_session(session, th):
        s = _sessions_db.get(th)
        if not s:
            return None
        from datetime import datetime
        return SimpleNamespace(
            user_id=s["user_id"],
            revoked_at="revoked" if s["revoked"] else None,
            expires_at=datetime(2099, 1, 1),
        )

    async def _revoke(session, th):
        s = _sessions_db.get(th)
        if s:
            s["revoked"] = True
        return s is not None

    async def _touch(session, th):
        pass

    async def _find_by_id(session, uid):
        for u in _users_db.values():
            if u["id"] == uid:
                return SimpleNamespace(
                    id=u["id"], username=u["username"],
                    display_name=u["display_name"], role=u["role"],
                    is_active=u["is_active"],
                )
        return None

    repo.find_user_by_username = _find_user
    repo.create_auth_session = _create_session
    repo.find_session_by_token_hash = _find_session
    repo.revoke_session = _revoke
    repo.touch_session = _touch
    repo.find_user_by_id = _find_by_id

    _seed()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    repo.find_user_by_username = _originals["find_user_by_username"]
    repo.create_auth_session = _originals["create_auth_session"]
    repo.find_session_by_token_hash = _originals["find_session_by_token_hash"]
    repo.revoke_session = _originals["revoke_session"]
    repo.touch_session = _originals["touch_session"]
    repo.find_user_by_id = _originals["find_user_by_id"]


# ============================================================
# 权限测试
# ============================================================

def test_admin_endpoint_403_for_member(client: TestClient) -> None:
    """普通成员访问管理接口返回 HTTP 403。"""
    login = client.post("/api/auth/login", json={
        "username": "member1", "password": "memb123",
    })
    assert login.status_code == 200
    client.cookies = login.cookies

    resp = client.get("/api/admin/health")
    assert resp.status_code == 403
    data = resp.json()
    assert data["code"] == "AUTH_FORBIDDEN"
    assert "trace_id" in data
    assert len(data["trace_id"]) > 0


def test_admin_endpoint_200_for_admin(client: TestClient) -> None:
    """管理员访问管理接口返回 HTTP 200。"""
    login = client.post("/api/auth/login", json={
        "username": "admin", "password": "admin123",
    })
    assert login.status_code == 200
    client.cookies = login.cookies

    resp = client.get("/api/admin/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "admin access granted" in data["message"]


def test_admin_endpoint_401_unauthenticated(client: TestClient) -> None:
    """未登录访问管理接口返回 HTTP 401。"""
    resp = client.get("/api/admin/health")
    assert resp.status_code == 401
    data = resp.json()
    assert data["code"] == "AUTH_SESSION_EXPIRED"
    assert "trace_id" in data


def test_admin_403_response_matches_error_contract(client: TestClient) -> None:
    """管理接口 403 响应符合公共错误契约 (code, message, retryable, trace_id)。"""
    login = client.post("/api/auth/login", json={
        "username": "member1", "password": "memb123",
    })
    client.cookies = login.cookies

    resp = client.get("/api/admin/health")
    assert resp.status_code == 403
    data = resp.json()
    # 公共错误契约四要素
    assert "code" in data
    assert "message" in data
    assert "retryable" in data
    assert "trace_id" in data
    assert data["retryable"] is False  # 权限不足不可重试
