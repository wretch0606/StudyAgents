"""
Worker 入口

职责：
  1. 启动时恢复过期任务
  2. 轮询 ingestion_jobs 表中 pending 任务
  3. 使用 SELECT ... FOR UPDATE SKIP LOCKED 获取任务
  4. 按阶段分派处理，持久化进度
  5. 发送心跳维持租约
"""

import asyncio
import logging
import signal
import sys
from worker.config import (
    WORKER_POLL_INTERVAL,
    WORKER_HEARTBEAT,
    ensure_dirs,
)
from worker.db.session import async_session_factory
from worker.ingestion.job_manager import JobManager

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

# 优雅退出标志
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"收到信号 {signum}，准备退出...")
    _shutdown = True


# ============================================================
# 主循环
# ============================================================

async def main():
    """Worker 主循环"""
    ensure_dirs()

    # 注册信号处理
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Worker 启动，正在恢复过期任务...")

    async with async_session_factory() as session:
        job_mgr = JobManager(session)
        recovered = await job_mgr.recover_stale_jobs()
        if recovered:
            logger.info(f"已恢复 {recovered} 个过期任务")
        await session.commit()

    logger.info(f"开始轮询，间隔 {WORKER_POLL_INTERVAL}s")

    last_heartbeat = 0
    iteration = 0

    while not _shutdown:
        try:
            async with async_session_factory() as session:
                job_mgr = JobManager(session)

                # 心跳
                if iteration - last_heartbeat >= WORKER_HEARTBEAT // WORKER_POLL_INTERVAL:
                    await job_mgr.send_heartbeat()
                    last_heartbeat = iteration

                # 获取待处理任务
                job = await job_mgr.claim_next()
                if job is None:
                    await session.commit()
                    await asyncio.sleep(WORKER_POLL_INTERVAL)
                    iteration += 1
                    continue

                logger.info(f"获取任务 {job.job_id}，阶段 {job.stage.value}")

                # TODO Day 2：在此调用 pipeline 按阶段处理
                # from worker.ingestion.pipeline import process_job
                # await process_job(job)

                await session.commit()

        except Exception as e:
            logger.error(f"主循环异常: {e}", exc_info=True)

        iteration += 1
        await asyncio.sleep(WORKER_POLL_INTERVAL)

    logger.info("Worker 已退出")


if __name__ == "__main__":
    asyncio.run(main())
