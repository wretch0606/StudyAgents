"""任务服务 — 状态机、租约、重试、恢复。Issue #11-3。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from apps.api.db.models.ingestion_job import (
    VALID_STATUSES,
    IngestionJob,
)

logger = logging.getLogger(__name__)

LEASE_SECONDS = 300  # 5 分钟


# ---- 状态机 ----

def validate_transition(current: str, target: str) -> None:
    """校验状态跳转合法性。不允许倒退或非法跳转。"""
    if target not in VALID_STATUSES:
        raise ValueError(f"非法状态: {target}")
    if current == target:
        return
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"非法状态跳转: {current} -> {target}")


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running"},
    "running": {"succeeded", "failed_retryable", "failed_permanent"},
    "failed_retryable": {"pending"},           # 重试 → 回到 pending
    "failed_permanent": set(),                  # 终态
    "succeeded": set(),                         # 终态
}


def determine_error_type(error: Exception) -> str:
    """判断异常是可重试还是永久失败。"""
    name = type(error).__name__
    msg = str(error).lower()
    permanent = {"ValueError", "FileNotFoundError", "FileValidationError"}
    if name in permanent:
        return "failed_permanent"
    if "unsupported" in msg or "corrupt" in msg or "format" in msg:
        return "failed_permanent"
    return "failed_retryable"


def validate_progress(current: float, new: float) -> None:
    """progress 不允许倒退或越界。"""
    if new < 0 or new > 100:
        raise ValueError(f"progress 越界: {new}")
    if new < current:
        raise ValueError(f"progress 倒退: {current} -> {new}")


# ---- 数据库操作 ----

async def claim_next_job(session) -> IngestionJob | None:
    """使用 SELECT FOR UPDATE SKIP LOCKED 获取下一个 pending 任务。

    设置 lease_until 防止并发 Worker 重复领取。
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.status == "pending")
        .order_by(IngestionJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = "running"
    job.attempts += 1
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    job.started_at = now
    job.updated_at = now
    await session.flush()
    return job


async def update_progress(
    session, job: IngestionJob, stage: str, progress: float,
    error_code: str | None = None, error_summary: str | None = None,
) -> None:
    validate_progress(job.progress, progress)
    job.stage = stage
    job.progress = progress
    job.error_code = error_code
    job.error_summary = error_summary
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()


async def complete_job(session, job: IngestionJob) -> None:
    validate_transition(job.status, "succeeded")
    now = datetime.now(UTC).replace(tzinfo=None)
    job.status = "succeeded"
    job.progress = 100.0
    job.finished_at = now
    job.updated_at = now
    await session.flush()


async def fail_job(
    session, job: IngestionJob,
    error: Exception | str,
    retryable: bool | None = None,
) -> str:
    """标记失败。自动判断是否可重试。"""
    if retryable is None:
        exc = error if isinstance(error, Exception) else RuntimeError(str(error))
        target = determine_error_type(exc)
    else:
        target = "failed_retryable" if retryable else "failed_permanent"

    # 超过重试上限强制永久失败
    if target == "failed_retryable" and job.max_retries_reached:
        target = "failed_permanent"

    validate_transition(job.status, target)
    now = datetime.now(UTC).replace(tzinfo=None)
    msg = str(error)[:1000]
    job.status = target
    job.error_code = type(error).__name__ if isinstance(error, Exception) else "ERROR"
    job.error_summary = msg
    job.finished_at = now
    job.updated_at = now
    await session.flush()
    return target


async def recover_stale_jobs(session) -> int:
    """恢复过期租约的任务：running → pending。"""
    now = datetime.now(UTC).replace(tzinfo=None)
    result = await session.execute(
        update(IngestionJob)
        .where(
            IngestionJob.status == "running",
            IngestionJob.lease_until < now,
        )
        .values(
            status="pending",
            lease_until=None,
            error_summary="租约过期，自动恢复",
            updated_at=now,
        )
    )
    return result.rowcount
