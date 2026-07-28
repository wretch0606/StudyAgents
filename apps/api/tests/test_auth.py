"""认证 API 测试 — 使用 dependency_overrides 替代 DB。

覆盖完整登录/注销/CSRF 流程。
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

from apps.api.services.auth import (  # noqa: E402
    hash_password,
)

# ---- 内存存储 ----
_users_db: dict[str, dict] = {}
_sessions_db: dict[str, dict] = {}


def _seed() -> None:
    _users_db.clear()
    _sessions_db.clear()
    # 重置限速器
    import apps.api.services.auth as auth_svc
    auth_svc._rate_store.clear()
    # 重置 CSRF store
    import apps.api.dependencies.auth as auth_dep
    auth_dep._csrf_store.clear()

    _users_db["admin"] = {
        "id": "u-admin-001", "username": "admin",
        "display_name": "Admin", "role": "admin",
        "password_hash": hash_password("admin123"), "is_active": True,
    }
    _users_db["member1"] = {
        "id": "u-memb-001", "username": "member1",
        "display_name": "Member One", "role": "member",
        "password_hash": hash_password("memb123"), "is_active": True,
    }


# ---- 模拟 DB Session ----

class _FakeSession:
    """模拟 AsyncSession — 仅实现 auth repo 所需方法。"""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self._objects: list = []

    def add(self, obj) -> None:
        self._objects.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        pass


async def _override_get_session():
    """用空 session 覆盖真实的 DB session。"""
    yield _FakeSession()


# ---- 构建测试 App ----

@pytest.fixture
def client() -> TestClient:
    from apps.api.db import session as db_session_module
    from apps.api.middleware.trace import TraceMiddleware, get_trace_id
    from apps.api.routers.auth import router as auth_router
    from apps.api.schemas.error import ApiError, ApiErrorResponse

    app = FastAPI()
    app.add_middleware(TraceMiddleware)
    app.include_router(auth_router, prefix="/api")

    # 覆盖 DB session
    app.dependency_overrides[db_session_module.get_session] = _override_get_session

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
        _sessions_db[th] = {"user_id": user_id, "username": next(
            (u["username"] for u in _users_db.values() if u["id"] == user_id), ""
        ), "role": next(
            (u["role"] for u in _users_db.values() if u["id"] == user_id), "member"
        ), "revoked": False}

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

    # restore
    repo.find_user_by_username = _originals["find_user_by_username"]
    repo.create_auth_session = _originals["create_auth_session"]
    repo.find_session_by_token_hash = _originals["find_session_by_token_hash"]
    repo.revoke_session = _originals["revoke_session"]
    repo.touch_session = _originals["touch_session"]
    repo.find_user_by_id = _originals["find_user_by_id"]


# ============================================================
# 登录
# ============================================================

def test_login_success(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["username"] == "member1"
    assert data["user"]["role"] == "member"
    assert "permissions" in data["user"]
    assert len(data["csrf_token"]) > 0


def test_login_unified_error(client: TestClient) -> None:
    r1 = client.post("/api/auth/login", json={"username": "member1", "password": "wrong"})
    r2 = client.post("/api/auth/login", json={"username": "nobody", "password": "any"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["code"] == r2.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_login_rate_limit(client: TestClient) -> None:
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "member1", "password": "bad"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "member1", "password": "bad"})
    assert r.status_code == 429
    assert r.json()["code"] == "AUTH_RATE_LIMITED"


# ============================================================
# me
# ============================================================

def test_me_authenticated(client: TestClient) -> None:
    login = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    client.cookies = login.cookies
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "member1"


def test_me_unauthenticated(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_no_password_leak(client: TestClient) -> None:
    login = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    client.cookies = login.cookies
    resp = client.get("/api/auth/me")
    assert "password" not in resp.json()
    assert "password_hash" not in resp.json()


# ============================================================
# CSRF
# ============================================================

def test_csrf_token_refresh(client: TestClient) -> None:
    login = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    client.cookies = login.cookies
    resp = client.get("/api/auth/csrf-token")
    assert resp.status_code == 200
    assert len(resp.json()["csrf_token"]) > 0


# ============================================================
# 注销
# ============================================================

def test_logout_invalidates(client: TestClient) -> None:
    login = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    client.cookies = login.cookies
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_logout_idempotent(client: TestClient) -> None:
    login = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    client.cookies = login.cookies
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200


# ============================================================
# 权限
# ============================================================

def test_admin_permissions(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    perms = resp.json()["user"]["permissions"]
    assert "admin:access" in perms
    assert "kb:manage" in perms


def test_member_permissions(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    perms = resp.json()["user"]["permissions"]
    assert "admin:access" not in perms


# ============================================================
# trace_id
# ============================================================

def test_error_has_trace_id(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "m", "password": "x"})
    assert "trace_id" in resp.json()
    assert len(resp.json()["trace_id"]) > 0
