"""B-D 导入适配器测试 — 使用 FakeIngestionAdapter，不访问真实文件/模型。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@pytest.fixture
def adapter():
    from apps.worker.ingestion_adapter import FakeIngestionAdapter
    return FakeIngestionAdapter()


# ---- 创建任务 ----

@pytest.mark.asyncio
async def test_create_job(adapter) -> None:
    job = await adapter.create_job("doc-001")
    assert job.job_id is not None
    assert job.document_id == "doc-001"
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_create_multiple_jobs(adapter) -> None:
    j1 = await adapter.create_job("d1")
    j2 = await adapter.create_job("d2")
    assert j1.job_id != j2.job_id


# ---- 任务领取 ----

@pytest.mark.asyncio
async def test_claim_next(adapter) -> None:
    await adapter.create_job("doc-a")
    job = await adapter.claim_next()
    assert job is not None
    assert job.status == "running"


@pytest.mark.asyncio
async def test_claim_next_empty(adapter) -> None:
    assert await adapter.claim_next() is None


# ---- 进度更新 ----

@pytest.mark.asyncio
async def test_update_progress(adapter) -> None:
    # B 的 IngestionStage.EXTRACTING 对应字符串 "extracting"
    job = await adapter.create_job("doc-p")
    await adapter.update_progress(job.job_id, "extracting", 30.0, "extracting...")
    assert adapter.jobs[job.job_id]["stage"] == "extracting"
    assert adapter.jobs[job.job_id]["progress"] == 30.0


# ---- 完成/失败 ----

@pytest.mark.asyncio
async def test_complete_job(adapter) -> None:
    job = await adapter.create_job("doc-c")
    await adapter.complete_job(job.job_id)
    assert adapter.jobs[job.job_id]["status"] == "succeeded"
    assert adapter.jobs[job.job_id]["progress"] == 100.0


@pytest.mark.asyncio
async def test_fail_job_retryable(adapter) -> None:
    job = await adapter.create_job("doc-f")
    await adapter.fail_job(job.job_id, "something went wrong", retryable=True)
    assert adapter.jobs[job.job_id]["status"] == "failed_retryable"
    assert "something went wrong" in adapter.jobs[job.job_id]["error"]


@pytest.mark.asyncio
async def test_fail_job_permanent(adapter) -> None:
    job = await adapter.create_job("doc-fp")
    await adapter.fail_job(job.job_id, "unsupported format", retryable=False)
    assert adapter.jobs[job.job_id]["status"] == "failed_permanent"


# ---- 重试 ----

@pytest.mark.asyncio
async def test_retry_job_success(adapter) -> None:
    job = await adapter.create_job("doc-r")
    await adapter.fail_job(job.job_id, "err", retryable=True)
    ok = await adapter.retry_job(job.job_id)
    assert ok is True
    assert adapter.jobs[job.job_id]["status"] == "pending"
    assert adapter.jobs[job.job_id]["attempts"] == 1


@pytest.mark.asyncio
async def test_retry_job_exceeds_max(adapter) -> None:
    job = await adapter.create_job("doc-rm")
    adapter.jobs[job.job_id]["attempts"] = 2  # 已达上限
    ok = await adapter.retry_job(job.job_id)
    assert ok is False
    assert adapter.jobs[job.job_id]["status"] == "failed_permanent"


@pytest.mark.asyncio
async def test_retry_nonexistent(adapter) -> None:
    assert await adapter.retry_job("nonexistent") is False


# ---- 恢复 ----

@pytest.mark.asyncio
async def test_recover_stale_jobs(adapter) -> None:
    j1 = await adapter.create_job("d1")
    j2 = await adapter.create_job("d2")
    adapter.jobs[j1.job_id]["status"] = "running"
    adapter.jobs[j2.job_id]["status"] = "succeeded"
    count = await adapter.recover_stale_jobs()
    assert count == 1
    assert adapter.jobs[j1.job_id]["status"] == "pending"
    assert adapter.jobs[j2.job_id]["status"] == "succeeded"  # 不受影响


# ---- Run Pipeline ----

@pytest.mark.asyncio
async def test_run_pipeline(adapter) -> None:
    job = await adapter.create_job("doc-run")
    await adapter.run_pipeline(job)
    assert adapter.jobs[job.job_id]["status"] == "succeeded"
    assert adapter.jobs[job.job_id]["progress"] == 100.0


# ---- Get Job ----

@pytest.mark.asyncio
async def test_get_job(adapter) -> None:
    job = await adapter.create_job("doc-get")
    found = await adapter.get_job(job.job_id)
    assert found is not None
    assert found.job_id == job.job_id
    assert await adapter.get_job("nonexistent") is None
