"""管理员资料与任务 API 测试 — 使用真实 PostgreSQL。需要 DATABASE_URL。"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


DATABASE_URL = os.getenv("DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


def _login(client, username: str, password: str) -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    client.cookies = r.cookies


@pytest.fixture
def client(tmp_path, monkeypatch):
    """使用真实 create_app + 测试文件目录。"""
    monkeypatch.setattr(
        "apps.api.services.file_storage.settings.files_root",
        str(tmp_path),
    )
    from apps.api.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ============================================================
# 认证与权限
# ============================================================

@needs_db
def test_unauth_upload_401(client) -> None:
    resp = client.post("/api/documents", files={
        "file": ("x.pdf", io.BytesIO(b"x"), "application/pdf"),
    })
    assert resp.status_code == 401


@needs_db
def test_unauth_list_401(client) -> None:
    assert client.get("/api/documents").status_code == 401


@needs_db
def test_member_upload_403(client) -> None:
    _login(client, "admin", "test-pass-123")
    resp = client.post("/api/documents", files={
        "file": ("test.pdf", io.BytesIO(b"%PDF-1.4 x" * 100), "application/pdf"),
    })
    assert resp.status_code == 403


@needs_db
def test_member_list_403(client) -> None:
    _login(client, "member_a", "test-pass-123")
    assert client.get("/api/documents").status_code == 403


@needs_db
def test_member_delete_403(client) -> None:
    _login(client, "member_a", "test-pass-123")
    assert client.delete("/api/documents/some-id").status_code == 403


@needs_db
def test_member_retry_403(client) -> None:
    _login(client, "member_a", "test-pass-123")
    assert client.post("/api/ingestion-jobs/some-id/retry").status_code == 403


# ============================================================
# 管理员上传
# ============================================================

@needs_db
def test_admin_upload_success(client) -> None:
    _login(client, "admin", "test-pass-123")
    resp = client.post("/api/documents", files={
        "file": ("lecture.pdf", io.BytesIO(b"%PDF-1.4 valid" * 200), "application/pdf"),
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["state"] == "accepted"
    assert "document" in data
    assert data["document"]["name"] == "lecture.pdf"
    assert "ingestion_job" in data
    assert data["ingestion_job"]["status"] == "pending"


@needs_db
def test_admin_upload_invalid_extension_415(client) -> None:
    _login(client, "admin", "test-pass-123")
    resp = client.post("/api/documents", files={
        "file": ("virus.exe", io.BytesIO(b"x"), "application/octet-stream"),
    })
    assert resp.status_code == 415


# ============================================================
# 管理员列表 / 详情
# ============================================================

@needs_db
def test_admin_list_documents(client) -> None:
    _login(client, "admin", "test-pass-123")
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@needs_db
def test_admin_get_document_detail(client) -> None:
    _login(client, "admin", "test-pass-123")
    # Upload first
    up = client.post("/api/documents", files={
        "file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 content" * 300), "application/pdf"),
    })
    assert up.status_code == 201
    doc_id = up.json()["document"]["id"]
    resp = client.get(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["document"]["name"] == "notes.pdf"


@needs_db
def test_admin_get_nonexistent_document_404(client) -> None:
    _login(client, "admin", "test-pass-123")
    resp = client.get(
        "/api/documents/00000000-0000-0000-0000-000000000000",
    )
    assert resp.status_code == 404


# ============================================================
# 管理员删除
# ============================================================

@needs_db
def test_admin_delete_document(client) -> None:
    _login(client, "admin", "test-pass-123")
    up = client.post("/api/documents", files={
        "file": ("tmp.pdf", io.BytesIO(b"%PDF-1.4 delete" * 200), "application/pdf"),
    })
    assert up.status_code == 201
    doc_id = up.json()["document"]["id"]
    resp = client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True


# ============================================================
# 任务查询 / 重试
# ============================================================

@needs_db
def test_admin_get_ingestion_job(client) -> None:
    _login(client, "admin", "test-pass-123")
    up = client.post("/api/documents", files={
        "file": ("jobtest.pdf", io.BytesIO(b"%PDF-1.4 job" * 200), "application/pdf"),
    })
    assert up.status_code == 201
    job_id = up.json()["ingestion_job"]["id"]
    resp = client.get(f"/api/ingestion-jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


@needs_db
def test_admin_retry_failed_job(client) -> None:
    _login(client, "admin", "test-pass-123")
    up = client.post("/api/documents", files={
        "file": ("retry.pdf", io.BytesIO(b"%PDF-1.4 retry" * 200), "application/pdf"),
    })
    assert up.status_code == 201
    job_id = up.json()["ingestion_job"]["id"]
    # 手动设置为 failed_retryable 以便测试 retry
    from apps.api.db.session import session_context
    from apps.api.db.models.ingestion_job import IngestionJob
    from sqlalchemy import select
    async def _set_failed():
        async with session_context() as db:
            r = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
            j = r.scalar_one()
            j.status = "failed_retryable"
            await db.commit()
    import asyncio
    asyncio.run(_set_failed())
    # 重试
    resp = client.post(f"/api/ingestion-jobs/{job_id}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


@needs_db
def test_admin_retry_non_retryable_rejected(client) -> None:
    _login(client, "admin", "test-pass-123")
    up = client.post("/api/documents", files={
        "file": ("noretry.pdf", io.BytesIO(b"%PDF-1.4 no" * 200), "application/pdf"),
    })
    assert up.status_code == 201
    job_id = up.json()["ingestion_job"]["id"]
    # succeeded 不可重试
    from apps.api.db.session import session_context
    from apps.api.db.models.ingestion_job import IngestionJob
    from sqlalchemy import select
    async def _set_succeeded():
        async with session_context() as db:
            r = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
            j = r.scalar_one()
            j.status = "succeeded"
            await db.commit()
    import asyncio
    asyncio.run(_set_succeeded())
    resp = client.post(f"/api/ingestion-jobs/{job_id}/retry")
    assert resp.status_code == 422
