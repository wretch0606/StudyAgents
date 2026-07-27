"""Worker 任务状态持久化集成测试 — 需要 DATABASE_URL。

验证 pending → running → succeeded/failed 状态写入 PostgreSQL。
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@pytest.fixture(autouse=True)
async def _dispose_engine():
    """每个测试后清理 DB engine 连接池（Windows ProactorEventLoop 兼容）。"""
    yield
    import apps.api.db.session as sess_mod
    try:
        eng = sess_mod._get_engine()
        await eng.dispose()
        sess_mod._engine = None
        sess_mod._sessionmaker = None
    except Exception:
        pass


async def _cleanup(doc_id: str, job_id: str) -> None:
    from apps.api.db.session import session_context

    async with session_context() as db:
        await db.execute(text("DELETE FROM ingestion_jobs WHERE id = :id"), {"id": job_id})
        await db.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
        await db.commit()


async def _setup(doc_id: str, job_id: str, stage: str) -> None:
    from apps.api.db.models.document import Document
    from apps.api.db.models.ingestion_job import IngestionJob
    from apps.api.db.session import session_context

    now = datetime.now(UTC).replace(tzinfo=None)
    async with session_context() as db:
        db.add(Document(
            id=doc_id, name="test.pdf", sha256=str(uuid.uuid4())[:8],
            mime="application/pdf", status="pending", version=1,
            created_at=now, updated_at=now,
        ))
        await db.flush()
        db.add(IngestionJob(
            id=job_id, document_id=doc_id, stage=stage, status="pending",
            progress=0.0, attempts=0, created_at=now, updated_at=now,
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_worker_processes_pending_job_to_succeeded() -> None:
    """Worker 处理 pending ingestion_job → succeeded。"""
    from apps.api.db.models.ingestion_job import IngestionJob
    from apps.api.db.session import session_context
    from apps.worker.main import Worker
    from apps.worker.pipeline import HandlerRegistry, WorkerResult

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    await _setup(doc_id, job_id, "test_stage")

    registry = HandlerRegistry()
    class H:
        async def handle(self, task):
            return WorkerResult(task_id=task.task_id, success=True)
    registry.register("test_stage", H())
    worker = Worker(registry)

    await worker._process_pending_jobs()

    async with session_context() as db:
        r = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
        job = r.scalar_one()
        assert job.status == "succeeded"
        assert job.progress == 100.0
        assert job.attempts == 1

    await _cleanup(doc_id, job_id)


@pytest.mark.asyncio
async def test_worker_marks_failed_on_handler_exception() -> None:
    """处理器异常 → DB status=failed + 可定位原因。"""
    from apps.api.db.models.ingestion_job import IngestionJob
    from apps.api.db.session import session_context
    from apps.worker.main import Worker
    from apps.worker.pipeline import HandlerRegistry

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    await _setup(doc_id, job_id, "failing_stage")

    registry = HandlerRegistry()
    class H:
        async def handle(self, task):
            raise RuntimeError("simulated failure")
    registry.register("failing_stage", H())
    worker = Worker(registry)

    await worker._process_pending_jobs()

    async with session_context() as db:
        r = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
        job = r.scalar_one()
        assert job.status == "failed"
        assert job.error is not None
        assert "HANDLER_EXCEPTION" in (job.error or "")
        assert job.updated_at is not None

    await _cleanup(doc_id, job_id)


@pytest.mark.asyncio
async def test_worker_marks_failed_on_unregistered_handler() -> None:
    """未注册 handler → status=failed + handler_not_configured。"""
    from apps.api.db.models.ingestion_job import IngestionJob
    from apps.api.db.session import session_context
    from apps.worker.main import Worker
    from apps.worker.pipeline import HandlerRegistry

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    await _setup(doc_id, job_id, "unregistered_stage")

    registry = HandlerRegistry()
    worker = Worker(registry)

    await worker._process_pending_jobs()

    async with session_context() as db:
        r = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
        job = r.scalar_one()
        assert job.status == "failed"
        assert job.error is not None
        assert "handler_not_configured" in (job.error or "")

    await _cleanup(doc_id, job_id)
