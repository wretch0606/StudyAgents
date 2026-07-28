"""
导入任务管理器

负责：
  - 创建/查询/更新导入任务
  - 租约获取与释放（SELECT ... FOR UPDATE SKIP LOCKED）
  - 过期任务恢复
  - 重试逻辑
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from worker.config import LEASE_DURATION
from worker.db.models import IngestionJob as IngestionJobModel
from worker.schemas import IngestionJob, IngestionStage, IngestionStatus

logger = logging.getLogger(__name__)


class JobManager:
    """导入任务 CRUD + 租约管理"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ---- 创建 ----

    async def create_job(self, document_id: str) -> IngestionJob:
        """创建导入任务"""
        job = IngestionJob(
            job_id=str(uuid4()),
            document_id=document_id,
            stage=IngestionStage.VALIDATING,
            status=IngestionStatus.PENDING,
            progress=0.0,
        )
        model = IngestionJobModel(
            id=job.job_id,
            document_id=job.document_id,
            stage=job.stage.value,
            status=job.status.value,
            progress=job.progress,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )
        self.session.add(model)
        return job

    # ---- 获取 ----

    async def claim_next(self) -> Optional[IngestionJob]:
        """
        获取下一个待处理任务。
        使用 SELECT ... FOR UPDATE SKIP LOCKED 避免并发冲突。
        """
        stmt = (
            select(IngestionJobModel)
            .where(IngestionJobModel.status == IngestionStatus.PENDING.value)
            .order_by(IngestionJobModel.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        # 锁定任务
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=LEASE_DURATION)
        row.status = IngestionStatus.RUNNING.value
        row.lease_until = lease_until
        row.lease_holder = "worker-1"  # TODO: 多 Worker 时使用 hostname
        row.attempts += 1
        row.started_at = now
        row.updated_at = now

        return self._model_to_job(row)

    # ---- 更新 ----

    async def update_progress(
        self,
        job_id: str,
        stage: IngestionStage,
        progress: float,
        error: Optional[str] = None,
    ):
        """更新任务阶段和进度"""
        stmt = (
            update(IngestionJobModel)
            .where(IngestionJobModel.id == job_id)
            .values(
                stage=stage.value,
                progress=progress,
                error_summary=error,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)

    async def complete_job(self, job_id: str):
        """标记任务成功"""
        now = datetime.now(timezone.utc)
        stmt = (
            update(IngestionJobModel)
            .where(IngestionJobModel.id == job_id)
            .values(
                stage=IngestionStage.COMPLETING.value,
                status=IngestionStatus.SUCCEEDED.value,
                progress=100.0,
                updated_at=now,
                completed_at=now,
            )
        )
        await self.session.execute(stmt)

    async def fail_job(self, job_id: str, error: str, retryable: bool = True):
        """标记任务失败"""
        stmt = (
            update(IngestionJobModel)
            .where(IngestionJobModel.id == job_id)
            .values(
                status=(
                    IngestionStatus.FAILED_RETRYABLE.value
                    if retryable
                    else IngestionStatus.FAILED_PERMANENT.value
                ),
                error_summary=error,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)

    # ---- 租约 ----

    async def extend_lease(self, job_id: str):
        """延长租约"""
        lease_until = datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION)
        stmt = (
            update(IngestionJobModel)
            .where(IngestionJobModel.id == job_id)
            .values(lease_until=lease_until, updated_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)

    async def send_heartbeat(self):
        """心跳：延长所有当前 Worker 持有任务的租约"""
        stmt = (
            update(IngestionJobModel)
            .where(
                IngestionJobModel.status == IngestionStatus.RUNNING.value,
                IngestionJobModel.lease_holder == "worker-1",
            )
            .values(
                lease_until=datetime.now(timezone.utc) + timedelta(seconds=LEASE_DURATION),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)

    # ---- 恢复 ----

    async def recover_stale_jobs(self) -> int:
        """
        恢复过期任务。
        将超过租约时间的 running 任务重置为 pending。
        """
        now = datetime.now(timezone.utc)
        stmt = (
            update(IngestionJobModel)
            .where(
                IngestionJobModel.status == IngestionStatus.RUNNING.value,
                IngestionJobModel.lease_until < now,
            )
            .values(
                status=IngestionStatus.PENDING.value,
                lease_until=None,
                lease_holder=None,
                error_summary="租约过期，自动恢复",
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    # ---- 重试 ----

    async def retry_job(self, job_id: str) -> bool:
        """重试失败任务。返回 True 表示可以重试。"""
        stmt = select(IngestionJobModel).where(IngestionJobModel.id == job_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return False

        if row.status not in (
            IngestionStatus.FAILED_RETRYABLE.value,
            IngestionStatus.PENDING.value,
        ):
            return False

        if row.attempts >= row.max_attempts:
            row.status = IngestionStatus.FAILED_PERMANENT.value
            row.error_summary = "超过最大重试次数"
            return False

        row.status = IngestionStatus.PENDING.value
        row.lease_until = None
        row.lease_holder = None
        row.error_summary = None
        row.updated_at = datetime.now(timezone.utc)
        return True

    # ---- 查询 ----

    async def get_job(self, job_id: str) -> Optional[IngestionJob]:
        """查询单个任务"""
        stmt = select(IngestionJobModel).where(IngestionJobModel.id == job_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._model_to_job(row)

    # ---- 转换 ----

    @staticmethod
    def _model_to_job(row: IngestionJobModel) -> IngestionJob:
        return IngestionJob(
            job_id=str(row.id),
            document_id=str(row.document_id),
            stage=IngestionStage(row.stage),
            status=IngestionStatus(row.status),
            progress=row.progress,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            error=row.error_summary,
            lease_until=row.lease_until.isoformat() if row.lease_until else None,
        )
