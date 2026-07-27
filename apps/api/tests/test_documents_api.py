"""管理员资料与任务 API 测试 — 使用 Fake session 和内存存储。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---- 内存存储 + 测试 App ----

_users_db: dict[str, dict] = {}
_sessions_db: dict[str, dict] = {}
_docs_db: dict[str, dict] = {}
_jobs_db: dict[str, dict] = {}


def _seed():
    _users_db.clear(); _sessions_db.clear(); _docs_db.clear(); _jobs_db.clear()
    import apps.api.services.auth as auth_svc
    auth_svc._rate_store.clear()
    import apps.api.dependencies.auth as auth_dep
    auth_dep._csrf_store.clear()
    _users_db["admin"] = {"id": "u-admin", "username": "admin", "display_name": "A", "role": "admin", "password_hash": auth_svc.hash_password("admin123"), "is_active": True}
    _users_db["member1"] = {"id": "u-memb", "username": "member1", "display_name": "M", "role": "member", "password_hash": auth_svc.hash_password("memb123"), "is_active": True}


@pytest.fixture
def client():
    # monkey-patch repos BEFORE importing anything that might cache them
    from types import SimpleNamespace

    import apps.api.repositories.auth as repo
    from apps.api.db.session import get_session
    from apps.api.middleware.trace import TraceMiddleware, get_trace_id
    from apps.api.routers import documents as doc_mod
    from apps.api.routers.auth import router as auth_router
    from apps.api.schemas.error import ApiError, ApiErrorResponse

    def _patch_repos():
        _originals = {k: getattr(repo, k) for k in [
            "find_user_by_username", "create_auth_session",
            "find_session_by_token_hash", "revoke_session",
            "touch_session", "find_user_by_id",
        ]}
        async def _fu(s, u):
            uu = _users_db.get(u)
            return SimpleNamespace(**uu) if uu else None
        async def _cs(s, uid, th, exp, ci=None):
            m = next((x for x in _users_db.values() if x["id"] == uid), None)
            _sessions_db[th] = {
                "user_id": uid,
                "username": m["username"] if m else "",
                "role": m["role"] if m else "member",
                "revoked": False,
            }
        async def _fs(s, th):
            ss = _sessions_db.get(th)
            if not ss:
                return None
            from datetime import datetime
            return SimpleNamespace(
                user_id=ss["user_id"],
                revoked_at="revoked" if ss["revoked"] else None,
                expires_at=datetime(2099, 1, 1),
            )
        async def _rv(s, th):
            ss = _sessions_db.get(th)
            if ss:
                ss["revoked"] = True
            return ss is not None
        async def _tc(s, th):
            pass
        async def _fbi(s, uid):
            for u in _users_db.values():
                if u["id"] == uid:
                    return SimpleNamespace(
                        id=u["id"], username=u["username"],
                        display_name=u["display_name"], role=u["role"],
                        is_active=u["is_active"],
                    )
            return None
        repo.find_user_by_username = _fu
        repo.create_auth_session = _cs
        repo.find_session_by_token_hash = _fs
        repo.revoke_session = _rv
        repo.touch_session = _tc
        repo.find_user_by_id = _fbi
        return _originals

    _originals = _patch_repos()

    app = FastAPI()
    app.add_middleware(TraceMiddleware)
    app.include_router(auth_router, prefix="/api")
    app.include_router(doc_mod.router, prefix="/api")
    app.include_router(doc_mod.job_router, prefix="/api")

    class FakeSess:
        committed = False
        def add(self, obj, **kw): pass
        async def flush(self): pass
        async def commit(self): self.committed = True
        async def rollback(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def execute(self, stmt): return _FakeResult(None)
    async def _override():
        yield FakeSess()
    app.dependency_overrides[get_session] = _override

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

    _seed()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    for k, v in _originals.items():
        setattr(repo, k, v)


class _FakeResult:
    def __init__(self, v): self._v = v
    def scalar_one_or_none(self): return self._v
    def scalar_one(self): return self._v
    def scalars(self):
        class A:
            def all(s): return []
        return A()


# ---- 登录辅助 ----

def _login_admin(client) -> None:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    client.cookies = r.cookies


def _login_member(client) -> None:
    r = client.post("/api/auth/login", json={"username": "member1", "password": "memb123"})
    assert r.status_code == 200
    client.cookies = r.cookies


# ============================================================
# 权限测试
# ============================================================

def test_member_upload_403(client) -> None:
    _login_member(client)
    resp = client.post("/api/documents", files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")})
    assert resp.status_code == 403


def test_admin_upload_success(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("apps.api.services.file_storage.settings.files_root", str(tmp_path))
    # 使用真实 DB session 需要 DATABASE_URL
    import os
    if not os.getenv("DATABASE_URL"):
        pytest.skip("需要 DATABASE_URL 进行上传测试")
    _login_admin(client)
    resp = client.post("/api/documents", files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 x" * 100), "application/pdf")})
    assert resp.status_code == 201
    assert resp.json()["state"] == "accepted"


def test_upload_invalid_extension(client) -> None:
    _login_admin(client)
    resp = client.post("/api/documents", files={"file": ("virus.exe", io.BytesIO(b"x"), "application/octet-stream")})
    assert resp.status_code == 415


def test_member_delete_403(client) -> None:
    _login_member(client)
    resp = client.delete("/api/documents/some-id")
    assert resp.status_code == 403


def test_member_list_403(client) -> None:
    _login_member(client)
    resp = client.get("/api/documents")
    assert resp.status_code == 403


def test_member_retry_403(client) -> None:
    _login_member(client)
    resp = client.post("/api/ingestion-jobs/some-id/retry")
    assert resp.status_code == 403


def test_unauth_upload_401(client) -> None:
    resp = client.post("/api/documents", files={"file": ("x.pdf", io.BytesIO(b"x"), "application/pdf")})
    assert resp.status_code == 401


def test_unauth_list_401(client) -> None:
    resp = client.get("/api/documents")
    assert resp.status_code == 401
