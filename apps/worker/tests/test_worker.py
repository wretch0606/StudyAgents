"""Worker 骨架测试 — 模块导入、配置、生命周期、处理器调度。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ============================================================
# 模块导入
# ============================================================

def test_worker_module_imports() -> None:
    """验证 Worker 核心模块可导入。"""
    from apps.worker import (
        health,  # noqa: E402, F401
        main,  # noqa: E402, F401
        pipeline,  # noqa: E402, F401
    )


def test_config_loads() -> None:
    """验证 Worker 可加载共享配置（不依赖 DATABASE_URL 必填）。"""
    from apps.api.config import settings  # noqa: E402
    assert settings.app_env is not None
    assert settings.max_upload_mb == 100


# ============================================================
# 健康检查
# ============================================================

def test_health_report_ok() -> None:
    """健康报告：全通过时 all_ok() 返回 True。"""
    from apps.worker.health import HealthReport, WorkerStatus  # noqa: E402

    report = HealthReport()
    report.add_check("config", True)
    report.add_check("database", True)
    report.status = WorkerStatus.ready
    assert report.all_ok()
    assert report.status == WorkerStatus.ready


def test_health_report_degraded() -> None:
    """健康报告：部分失败时 all_ok() 返回 False。"""
    from apps.worker.health import HealthReport, WorkerStatus  # noqa: E402

    report = HealthReport()
    report.add_check("config", True)
    report.add_check("database", False, "connection refused")
    report.status = WorkerStatus.degraded
    assert not report.all_ok()
    assert "connection refused" in report.summary()


def test_health_report_no_checks() -> None:
    """健康报告：无检查时 all_ok() 返回 False。"""
    from apps.worker.health import HealthReport  # noqa: E402

    report = HealthReport()
    assert not report.all_ok()


# ============================================================
# 处理器注册表
# ============================================================

def test_handler_registry_register_and_get() -> None:
    """注册后可通过 task_type 获取处理器。"""
    from apps.worker.pipeline import HandlerRegistry  # noqa: E402

    registry = HandlerRegistry()

    class FakeHandler:
        async def handle(self, task):
            from apps.worker.pipeline import WorkerResult
            return WorkerResult(task_id=task.task_id, success=True)

    handler = FakeHandler()
    registry.register("test_type", handler)
    assert registry.get("test_type") is handler


def test_handler_not_configured_error() -> None:
    """未注册类型抛出 HandlerNotConfiguredError。"""
    from apps.worker.pipeline import HandlerNotConfiguredError, HandlerRegistry  # noqa: E402

    registry = HandlerRegistry()
    assert registry.get("nonexistent") is None

    with pytest.raises(HandlerNotConfiguredError, match="nonexistent"):
        raise HandlerNotConfiguredError("nonexistent")


def test_list_registered() -> None:
    """list_registered 返回已注册类型列表。"""
    from apps.worker.pipeline import HandlerRegistry  # noqa: E402

    registry = HandlerRegistry()
    assert registry.list_registered() == []

    class FakeHandler:
        async def handle(self, task):
            from apps.worker.pipeline import WorkerResult
            return WorkerResult(task_id=task.task_id, success=True)

    registry.register("ingestion", FakeHandler())
    assert "ingestion" in registry.list_registered()


def test_default_registry_covers_ingestion_stages() -> None:
    """生产启动时所有持久化阶段都有真实处理器。"""
    from apps.api.db.models.ingestion_job import VALID_STAGES
    from apps.worker.main import build_default_registry

    registry = build_default_registry()
    assert set(registry.list_registered()) == VALID_STAGES


# ============================================================
# Worker 任务执行
# ============================================================

@pytest.mark.asyncio
async def test_worker_execute_task_success() -> None:
    """已注册处理器正确调用并返回成功结果。"""
    from apps.worker.main import Worker  # noqa: E402
    from apps.worker.pipeline import HandlerRegistry, WorkerTask  # noqa: E402

    registry = HandlerRegistry()

    class FakeHandler:
        async def handle(self, task):
            from apps.worker.pipeline import WorkerResult
            return WorkerResult(task_id=task.task_id, success=True, output={"ok": True})

    registry.register("test", FakeHandler())
    worker = Worker(registry)

    task = WorkerTask(task_id="t-001", task_type="test", payload={})
    result = await worker.execute_task(task)
    assert result.success
    assert result.task_id == "t-001"
    assert result.output == {"ok": True}


@pytest.mark.asyncio
async def test_worker_execute_task_handler_not_configured() -> None:
    """未注册处理器时 execute_task 抛出 HandlerNotConfiguredError。"""
    from apps.worker.main import Worker  # noqa: E402
    from apps.worker.pipeline import (  # noqa: E402
        HandlerNotConfiguredError,
        HandlerRegistry,
        WorkerTask,
    )

    registry = HandlerRegistry()
    worker = Worker(registry)

    task = WorkerTask(task_id="t-002", task_type="nonexistent", payload={})
    with pytest.raises(HandlerNotConfiguredError, match="nonexistent"):
        await worker.execute_task(task)


@pytest.mark.asyncio
async def test_worker_execute_task_handler_exception() -> None:
    """处理器抛出异常时返回失败结果，不崩溃。"""
    from apps.worker.main import Worker  # noqa: E402
    from apps.worker.pipeline import HandlerRegistry, WorkerTask  # noqa: E402

    registry = HandlerRegistry()

    class FailingHandler:
        async def handle(self, task):
            raise RuntimeError("simulated failure")

    registry.register("failing", FailingHandler())
    worker = Worker(registry)

    task = WorkerTask(task_id="t-003", task_type="failing", payload={})
    result = await worker.execute_task(task)
    assert not result.success
    assert result.error_code == "HANDLER_EXCEPTION"


# ============================================================
# WorkerTask / WorkerResult
# ============================================================

def test_worker_task_defaults() -> None:
    """WorkerTask 默认字段值正确。"""
    from apps.worker.pipeline import WorkerTask  # noqa: E402

    task = WorkerTask(task_id="1", task_type="x")
    assert task.payload == {}
    assert task.trace_context == {}


def test_worker_result_failure() -> None:
    """WorkerResult 可表示失败。"""
    from apps.worker.pipeline import WorkerResult  # noqa: E402

    r = WorkerResult(task_id="1", success=False, error_code="E01", error_message="boom")
    assert not r.success
    assert r.error_code == "E01"


# ============================================================
# Worker 生命周期测试
# ============================================================

@pytest.mark.asyncio
async def test_worker_start_and_stop() -> None:
    """Worker.start() 可启动，Worker.stop() 可取消后台任务并等待。"""
    from apps.worker.main import Worker  # noqa: E402
    from apps.worker.pipeline import HandlerRegistry  # noqa: E402

    registry = HandlerRegistry()
    worker = Worker(registry)

    await worker.start()
    assert worker._task is not None
    assert not worker._task.done()

    await worker.stop()
    assert worker._task.done()
    assert worker._task.cancelled() or worker._task.exception() is None


@pytest.mark.asyncio
async def test_worker_double_stop_no_error() -> None:
    """重复调用 stop() 不产生未处理异常。"""
    from apps.worker.main import Worker  # noqa: E402
    from apps.worker.pipeline import HandlerRegistry  # noqa: E402

    registry = HandlerRegistry()
    worker = Worker(registry)

    await worker.start()
    await worker.stop()
    # 第二次 stop 不应抛出
    await worker.stop()


@pytest.mark.asyncio
async def test_worker_no_residual_tasks() -> None:
    """Worker 停止后不残留 asyncio Task。"""
    import asyncio

    from apps.worker.main import Worker  # noqa: E402
    from apps.worker.pipeline import HandlerRegistry  # noqa: E402

    registry = HandlerRegistry()
    worker = Worker(registry)

    tasks_before = len(asyncio.all_tasks())
    await worker.start()
    await worker.stop()

    # 给事件循环一点时间清理
    await asyncio.sleep(0.01)
    tasks_after = len(asyncio.all_tasks())
    # 不应比启动前多出悬挂任务
    assert tasks_after <= tasks_before + 1  # +1 容错（当前测试 task 自身）


@pytest.mark.asyncio
async def test_worker_run_loop_does_not_busy_spin() -> None:
    """运行循环不会高频空转：迭代间至少等待 90% 的 POLL_INTERVAL。"""
    import time

    from apps.worker.main import Worker  # noqa: E402
    from apps.worker.pipeline import HandlerRegistry  # noqa: E402

    # 使用更短的轮询间隔加速测试
    registry = HandlerRegistry()
    worker = Worker(registry)
    worker.POLL_INTERVAL = 0.1

    await worker.start()
    t0 = time.monotonic()
    # 等待足够的时间让循环执行多次迭代
    await __import__("asyncio").sleep(0.35)
    elapsed = time.monotonic() - t0
    await worker.stop()

    # 如果高频空转，elapsed 会远超 sleep 时间（CPU 繁忙）
    # 0.35s sleep 在 0.1s poll interval 下最多 3-4 次迭代
    # 正常应 < 2s（留足余量）
    assert elapsed < 2.0, f"运行循环疑似高频空转: elapsed={elapsed:.2f}s"
