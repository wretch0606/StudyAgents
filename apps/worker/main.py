"""Worker 进程入口。

启动:  uv run python -m apps.worker.main
检查:  uv run python -m apps.worker.main --check
停止:  SIGINT / SIGTERM

生命周期：启动→加载配置→日志初始化→DB连接检查→注册处理器→运行/轮询→优雅停止。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# 确保项目根在 Python path
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.config import settings  # noqa: E402
from apps.api.middleware.logging import setup_logging  # noqa: E402
from apps.worker.health import HealthReport, WorkerStatus  # noqa: E402
from apps.worker.pipeline import (  # noqa: E402
    HandlerNotConfiguredError,
    HandlerRegistry,
    WorkerResult,
    WorkerTask,
)

logger = logging.getLogger("worker")


# ============================================================
# 健康检查
# ============================================================

async def _check_health() -> HealthReport:
    """执行健康检查，返回报告。"""
    report = HealthReport()
    report.status = WorkerStatus.starting

    # 1. 配置检查
    if settings.database_url:
        report.add_check("config", True)
    else:
        report.add_check("config", False, "DATABASE_URL not configured")

    # 2. 数据库连接
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from apps.api.db.session import _build_async_url

        url = _build_async_url()
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        report.add_check("database", True)
    except Exception as exc:
        report.add_check("database", False, type(exc).__name__)

    if report.all_ok():
        report.status = WorkerStatus.ready
    else:
        report.status = WorkerStatus.degraded

    return report


# ============================================================
# 运行循环
# ============================================================

class Worker:
    """Worker 实例 — 管理生命周期和任务调度。"""

    POLL_INTERVAL = 5.0  # 任务轮询间隔（秒）

    def __init__(self, registry: HandlerRegistry) -> None:
        self.registry = registry
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动 Worker：检查 DB，确认处理器状态，开始轮询。"""
        logger.info("worker starting")
        report = await _check_health()
        logger.info("health: %s", report.summary())

        registered = self.registry.list_registered()
        if registered:
            logger.info("registered handlers: %s", registered)
        else:
            logger.warning("no handlers registered — worker will reject all tasks")

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        """主循环：轮询 DB 中的 pending ingestion_jobs，处理并更新状态。"""
        logger.info("run loop started (poll_interval=%.1fs)", self.POLL_INTERVAL)
        while not self._stop_event.is_set():
            try:
                await self._process_pending_jobs()
                await asyncio.sleep(self.POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("run loop iteration error")
                await asyncio.sleep(self.POLL_INTERVAL)
        logger.info("run loop exited")

    async def _process_pending_jobs(self) -> None:
        """使用租约获取 pending 任务，通过 B 适配器执行并持久化。

        Issue #11：SELECT FOR UPDATE SKIP LOCKED + 重试 + 恢复。
        """
        from apps.api.db.session import session_context
        from apps.worker.services.job_service import (
            claim_next_job,
            complete_job,
            fail_job,
            recover_stale_jobs,
            update_progress,
        )

        try:
            async with session_context() as db_session:
                # 恢复过期任务
                recovered = await recover_stale_jobs(db_session)
                if recovered:
                    logger.info("recovered %d stale jobs", recovered)
                await db_session.commit()

            async with session_context() as db_session:
                # 领取任务（带锁）
                job = await claim_next_job(db_session)
                if job is None:
                    await db_session.commit()
                    return

                logger.info(
                    "claimed job %s doc=%s attempt=%d",
                    job.id, job.document_id, job.attempts,
                )
                await db_session.commit()

            # 执行任务（独立事务，避免长事务）
            async with session_context() as db_session:
                # 重新加载 job
                from apps.api.db.models.ingestion_job import IngestionJob
                result = await db_session.execute(
                    __import__("sqlalchemy").select(IngestionJob).where(
                        IngestionJob.id == job.id
                    )
                )
                job = result.scalar_one()

                try:
                    # 通过 B 适配器执行阶段
                    if self.registry.list_registered():
                        task = WorkerTask(
                            task_id=str(job.id),
                            task_type=job.stage,
                            payload={"document_id": str(job.document_id)},
                        )
                        worker_result = await self.execute_task(task)
                        if worker_result.success:
                            await complete_job(db_session, job)
                        else:
                            await fail_job(
                                db_session, job,
                                RuntimeError(worker_result.error_message or "unknown"),
                            )
                    else:
                        # 无处理器：标记为可重试（等待 B 接入）
                        await update_progress(
                            db_session, job, job.stage, job.progress,
                            error_code="NO_HANDLER",
                            error_summary="handler_not_configured",
                        )
                        await fail_job(
                            db_session, job,
                            RuntimeError("handler_not_configured"),
                            retryable=True,
                        )
                except Exception as exc:
                    await fail_job(db_session, job, exc)
                    logger.exception("job %s failed", job.id)

                await db_session.commit()

        except Exception:
            logger.exception("failed to process pending jobs")

    async def execute_task(self, task: WorkerTask) -> WorkerResult:
        """执行单个任务：路由到已注册的处理器。

        由外部任务源（Issue #11）调用。
        """
        handler = self.registry.get(task.task_type)
        if handler is None:
            raise HandlerNotConfiguredError(task.task_type)

        logger.info("task started: id=%s type=%s", task.task_id, task.task_type)
        try:
            result = await handler.handle(task)
            if result.success:
                logger.info("task succeeded: id=%s", task.task_id)
            else:
                logger.warning(
                    "task failed: id=%s code=%s msg=%s",
                    task.task_id, result.error_code, result.error_message,
                )
            return result
        except Exception as exc:
            logger.exception("task exception: id=%s", task.task_id)
            return WorkerResult(
                task_id=task.task_id,
                success=False,
                error_code="HANDLER_EXCEPTION",
                error_message=str(exc)[:500],
            )

    async def stop(self) -> None:
        """优雅停止：发送停止信号，等待当前轮询退出。"""
        logger.info("worker stopping")
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("worker stopped")


# ============================================================
# CLI
# ============================================================

def _setup_signal_handlers(worker: Worker, loop: asyncio.AbstractEventLoop) -> None:
    """注册 SIGINT/SIGTERM 处理器。"""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass


async def _run_main(check_only: bool, database_url: str = "") -> None:
    """主入口。"""
    setup_logging()

    registry = HandlerRegistry()
    worker = Worker(registry)

    if check_only:
        report = await _check_health()
        print(report.summary())
        if report.all_ok():
            logger.info("health check: all OK")
        else:
            logger.error("health check: failures detected")
            sys.exit(1)
        return

    await worker.start()
    logger.info("worker ready — press Ctrl+C to stop")

    # Windows 兼容：使用 asyncio.Event 等待
    stop_event = asyncio.Event()

    def _stop():
        asyncio.create_task(worker.stop())
        stop_event.set()

    loop = asyncio.get_running_loop()
    _setup_signal_handlers(worker, loop)
    # 后备：KeyboardInterrupt
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("keyboard interrupt received")
    finally:
        await worker.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="StudyAgents Worker")
    parser.add_argument(
        "--check", action="store_true",
        help="Run health check and exit (non-zero if unhealthy).",
    )
    args = parser.parse_args()

    try:
        asyncio.run(_run_main(check_only=args.check))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
