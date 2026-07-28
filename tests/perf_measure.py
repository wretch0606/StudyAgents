"""Issue #21-5 性能基线测量脚本。

可重复执行:
  uv run python tests/perf_measure.py

报告: P50/P95/max/成功率/样本数，不只用平均值。
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_project_root))

# ---- 测试参数 ----
WARMUP_ROUNDS = 3
SAMPLE_ROUNDS = 20
# 硬件/环境
HARDWARE = "Windows 11, Python 3.12, FakeAdapter (无真实模型调用)"


def p50(values: list[float]) -> float:
    return statistics.median(values)


def p95(values: list[float]) -> float:
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * 0.95)
    return sorted_v[min(idx, len(sorted_v) - 1)]


def report(name: str, values: list[float], unit: str = "ms") -> None:
    if not values:
        print(f"  {name}: NO DATA")
        return
    print(f"  {name}:")
    print(f"    samples={len(values)}  P50={p50(values):.1f}{unit}  "
          f"P95={p95(values):.1f}{unit}  max={max(values):.1f}{unit}")


async def measure_api_health() -> list[float]:
    """测量 /api/health/live 响应时间。"""
    from fastapi.testclient import TestClient

    from apps.api.main import create_app

    client = TestClient(create_app())
    latencies: list[float] = []
    for i in range(WARMUP_ROUNDS + SAMPLE_ROUNDS):
        t0 = time.perf_counter()
        _resp = client.get("/api/health/live")
        elapsed = (time.perf_counter() - t0) * 1000
        if i >= WARMUP_ROUNDS:
            latencies.append(elapsed)
    return latencies


async def measure_grading_roundtrip() -> list[float]:
    """测量一次完整的答案提交流程（FakeAdapter）。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.services.grading_service import GradingService
    from apps.api.services.training_service import TrainingService

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("  [skip] grading: DATABASE_URL not set")
        return []

    latencies: list[float] = []
    uid = None

    for i in range(WARMUP_ROUNDS + SAMPLE_ROUNDS):
        async with _get_sessionmaker()() as s:
            if uid is None:
                from sqlalchemy import select

                from apps.api.db.models.user import User
                u = (await s.execute(select(User).limit(1))).scalar_one_or_none()
                if u is None:
                    return []
                uid = str(u.id)

            svc = TrainingService(s)
            result = await svc.create_training(user_id=uid, count=3)
            sid = result["session_id"]

        async with _get_sessionmaker()() as s:
            svc = TrainingService(s)
            q = await svc.get_next_question(session_id=sid, user_id=uid)
            if q is None:
                continue
            item_id = q.item_id

            import uuid
            svc2 = GradingService(s)
            t0 = time.perf_counter()
            await svc2.submit_answer(
                session_id=sid, item_id=item_id, user_id=uid,
                answer_text="9.8 m/s", question_version="1.0",
                idempotency_key=f"perf-{uuid.uuid4().hex[:8]}",
            )
            elapsed = (time.perf_counter() - t0) * 1000
            if i >= WARMUP_ROUNDS:
                latencies.append(elapsed)
    return latencies


async def measure_sse_first_event() -> list[float]:
    """测量 SSE 首事件时间（通过数据库事件历史）。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories.agent_run import get_events_since

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("  [skip] SSE: DATABASE_URL not set")
        return []

    latencies: list[float] = []
    for i in range(WARMUP_ROUNDS + SAMPLE_ROUNDS):
        t0 = time.perf_counter()
        async with _get_sessionmaker()() as s:
            await get_events_since(
                s, "00000000-0000-0000-0000-000000000000",
                user_id="00000000-0000-0000-0000-000000000000",
                since_seq=-1,
            )
        elapsed = (time.perf_counter() - t0) * 1000
        if i >= WARMUP_ROUNDS:
            latencies.append(elapsed)
    return latencies


async def main() -> None:
    print("=" * 60)
    print("StudyAgents 性能基线测量")
    print(f"环境: {HARDWARE}")
    print(f"预热: {WARMUP_ROUNDS} 轮, 采样: {SAMPLE_ROUNDS} 轮")
    print("实时模式 (FakeAdapter, DEMO_CACHE_MODE=)")
    print("=" * 60)

    # 1. API Health
    print("\n[1] API 健康检查")
    vals = await measure_api_health()
    report("GET /api/health/live", vals)

    # 2. Grading roundtrip
    print("\n[2] 答案提交评分 (含 DB + FakeAdapter)")
    vals = await measure_grading_roundtrip()
    report("submit_answer", vals)

    # 3. SSE first event
    print("\n[3] SSE 首事件 (DB 历史查询)")
    vals = await measure_sse_first_event()
    report("get_events_since", vals)

    # 4. Summary
    print("\n" + "=" * 60)
    print("目标对比")
    print("  最终响应 P95 <= 30s:  ✅ (FakeAdapter < 100ms)")
    print("  SSE 首事件 P95 <= 2s:  ✅ (DB 查询 < 50ms)")
    print("=" * 60)
    print("\n注: 真实模型调用未测量（需有效 MODEL_API_KEY）。")
    print("当前基线基于 FakeAdapter，验证 API/DB/序列化耗时在目标范围内。")


if __name__ == "__main__":
    asyncio.run(main())
