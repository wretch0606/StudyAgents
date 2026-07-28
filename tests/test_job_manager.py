"""
任务管理器测试

覆盖：创建/获取/更新/完成/失败/租约/恢复/重试/心跳/幂等
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.ingestion.job_manager import JobManager
from worker.schemas import IngestionStage, IngestionStatus
from worker.db.models import IngestionJob as IngestionJobModel


class TestJobCreation:
    """任务创建"""

    @pytest.mark.asyncio
    async def test_create_job(self):
        session = AsyncMock()
        mgr = JobManager(session)

        job = await mgr.create_job("doc-001")
        assert job.document_id == "doc-001"
        assert job.stage == IngestionStage.VALIDATING
        assert job.status == IngestionStatus.PENDING
        assert job.progress == 0.0
        session.add.assert_called_once()


class TestJobClaim:
    """任务获取"""

    @pytest.mark.asyncio
    async def test_claim_job_success(self):
        session = AsyncMock()
        mock_job = MagicMock(spec=IngestionJobModel)
        mock_job.id = "job-001"
        mock_job.document_id = "doc-001"
        mock_job.stage = "validating"
        mock_job.status = "pending"
        mock_job.progress = 0.0
        mock_job.attempts = 0
        mock_job.max_attempts = 3
        mock_job.error_summary = None
        mock_job.lease_until = None

        # Mock SELECT ... FOR UPDATE SKIP LOCKED
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        job = await mgr.claim_next()

        assert job is not None
        assert job.job_id == "job-001"
        # 任务应被锁定为 running
        assert mock_job.status == "running"
        assert mock_job.lease_until is not None

    @pytest.mark.asyncio
    async def test_claim_none_when_empty(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        job = await mgr.claim_next()
        assert job is None


class TestJobProgress:
    """进度更新"""

    @pytest.mark.asyncio
    async def test_update_progress(self):
        session = AsyncMock()
        mgr = JobManager(session)

        await mgr.update_progress("job-001", IngestionStage.CHUNKING, 70.0)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_with_error(self):
        session = AsyncMock()
        mgr = JobManager(session)

        await mgr.update_progress(
            "job-001", IngestionStage.EXTRACTING,
            progress=30.0, error="解析失败：文件损坏"
        )
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_job(self):
        session = AsyncMock()
        mgr = JobManager(session)

        await mgr.complete_job("job-001")
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_retryable(self):
        session = AsyncMock()
        mgr = JobManager(session)

        await mgr.fail_job("job-001", "timeout", retryable=True)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_permanent(self):
        session = AsyncMock()
        mgr = JobManager(session)

        await mgr.fail_job("job-001", "unsupported format", retryable=False)
        session.execute.assert_called_once()


class TestLease:
    """租约管理"""

    @pytest.mark.asyncio
    async def test_extend_lease(self):
        session = AsyncMock()
        mgr = JobManager(session)

        await mgr.extend_lease("job-001")
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_heartbeat(self):
        session = AsyncMock()
        mgr = JobManager(session)

        await mgr.send_heartbeat()
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_stale(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3  # 恢复了 3 个过期任务
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        count = await mgr.recover_stale_jobs()
        assert count == 3


class TestRetry:
    """重试逻辑"""

    @pytest.mark.asyncio
    async def test_retry_failed_retryable(self):
        session = AsyncMock()
        mock_job = MagicMock(spec=IngestionJobModel)
        mock_job.status = "failed_retryable"
        mock_job.attempts = 1
        mock_job.max_attempts = 3

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        ok = await mgr.retry_job("job-001")
        assert ok
        assert mock_job.status == "pending"

    @pytest.mark.asyncio
    async def test_retry_exceeds_max(self):
        session = AsyncMock()
        mock_job = MagicMock(spec=IngestionJobModel)
        mock_job.status = "failed_retryable"
        mock_job.attempts = 3
        mock_job.max_attempts = 3

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        ok = await mgr.retry_job("job-001")
        assert not ok
        assert mock_job.status == "failed_permanent"

    @pytest.mark.asyncio
    async def test_cannot_retry_succeeded(self):
        session = AsyncMock()
        mock_job = MagicMock(spec=IngestionJobModel)
        mock_job.status = "succeeded"
        mock_job.attempts = 1
        mock_job.max_attempts = 3

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        ok = await mgr.retry_job("job-001")
        assert not ok

    @pytest.mark.asyncio
    async def test_retry_nonexistent(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        ok = await mgr.retry_job("nonexistent")
        assert not ok


class TestJobQuery:
    """任务查询"""

    @pytest.mark.asyncio
    async def test_get_job(self):
        session = AsyncMock()
        mock_job = MagicMock(spec=IngestionJobModel)
        mock_job.id = "job-001"
        mock_job.document_id = "doc-001"
        mock_job.stage = "extracting"
        mock_job.status = "running"
        mock_job.progress = 50.0
        mock_job.attempts = 1
        mock_job.max_attempts = 3
        mock_job.error_summary = None
        mock_job.lease_until = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        job = await mgr.get_job("job-001")
        assert job is not None
        assert job.job_id == "job-001"
        assert job.stage == IngestionStage.EXTRACTING
        assert job.status == IngestionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_job_not_found(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        mgr = JobManager(session)
        job = await mgr.get_job("nonexistent")
        assert job is None
