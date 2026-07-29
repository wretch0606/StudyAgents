"""Demo Cache 测试 — 缓存模式命中/未命中、实时模式不误启、私有字段拒绝、demo 标记。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def test_is_demo_mode_default_off() -> None:
    """默认实时模式。"""
    from apps.api.services.demo_cache import is_demo_mode
    assert not is_demo_mode()


def test_demo_cache_get_miss() -> None:
    """未命中返回 None。"""
    from apps.api.services.demo_cache import DemoCache
    cache = DemoCache()
    result = cache.get("knowledge", "v1", [{"role": "user", "content": "test"}])
    assert result is None


def test_demo_cache_set_get() -> None:
    """写入后命中，含 _demo=True 标记。"""
    from apps.api.services.demo_cache import DemoCache
    cache = DemoCache()
    messages = [{"role": "user", "content": "什么是干涉"}]
    cache.set("knowledge", "v1", messages, {"answer": "干涉是..."})
    result = cache.get("knowledge", "v1", messages)
    assert result is not None
    assert result["_demo"] is True
    assert result["answer"] == "干涉是..."


def test_demo_cache_different_key() -> None:
    """不同输入产生不同缓存键。"""
    from apps.api.services.demo_cache import DemoCache
    cache = DemoCache()
    cache.set("knowledge", "v1", [{"role": "user", "content": "A"}], {"x": 1})
    result = cache.get("knowledge", "v1", [{"role": "user", "content": "B"}])
    assert result is None


def test_demo_cache_rejects_private_fields() -> None:
    """含私有字段的内容拒绝缓存。"""
    from apps.api.services.demo_cache import DemoCache
    cache = DemoCache()
    with pytest.raises(ValueError, match="expected_answer"):
        cache.set("evaluator", "v1", [], {"expected_answer": "42"})
    with pytest.raises(ValueError, match="rubric"):
        cache.set("evaluator", "v1", [], {"rubric": [...]})
    with pytest.raises(ValueError, match="step_scores"):
        cache.set("evaluator", "v1", [], {"step_scores": [...]})


def test_demo_cache_size() -> None:
    """size 属性正确。"""
    from apps.api.services.demo_cache import DemoCache
    cache = DemoCache()
    assert cache.size == 0
    cache.set("k", "v1", [{"role": "user", "content": "a"}], {})
    assert cache.size == 1


def test_demo_cache_clear() -> None:
    """clear 清空所有缓存。"""
    from apps.api.services.demo_cache import DemoCache
    cache = DemoCache()
    cache.set("k", "v1", [{"role": "user", "content": "a"}], {})
    cache.clear()
    assert cache.size == 0


def test_singleton() -> None:
    """模块级单例。"""
    from apps.api.services.demo_cache import DemoCache, get_demo_cache
    c1 = get_demo_cache()
    c2 = get_demo_cache()
    assert c1 is c2
    assert isinstance(c1, DemoCache)


@pytest.mark.asyncio
async def test_realtime_mode_provider_not_cache() -> None:
    """实时模式下 FakeAdapter provider 不是 demo-cache。"""
    from pydantic import BaseModel

    class TestOutput(BaseModel):
        answer: str = ""

    old = os.environ.pop("DEMO_CACHE_MODE", None)
    try:
        from apps.api.services.model_gateway import FakeAdapter, ModelMessage
        adapter = FakeAdapter(responses=[TestOutput(answer="ok")])
        result = await adapter.invoke_structured(
            run_id="r1", trace_id="t1", agent="test", prompt_version="v1",
            messages=[ModelMessage(role="user", content="hello")],
            output_schema=TestOutput, temperature=0.0,
        )
        assert result is not None
        assert result.provider != "demo-cache"
    finally:
        if old is not None:
            os.environ["DEMO_CACHE_MODE"] = old


@pytest.mark.asyncio
async def test_demo_mode_cache_miss_raises() -> None:
    """缓存模式未命中抛出 DEMO_CACHE_MISS 错误。"""
    from pydantic import BaseModel

    class TestOutput(BaseModel):
        answer: str = ""

    from apps.api.services.model_gateway import FakeAdapter, ModelGatewayError, ModelMessage
    os.environ["DEMO_CACHE_MODE"] = "1"
    try:
        adapter = FakeAdapter(responses=[])
        with pytest.raises(ModelGatewayError, match="演示缓存未命中"):
            await adapter.invoke_structured(
                run_id="r1", trace_id="t1", agent="unknown", prompt_version="v1",
                messages=[ModelMessage(role="user", content="never seen")],
                output_schema=TestOutput, temperature=0.0,
            )
    finally:
        os.environ.pop("DEMO_CACHE_MODE", None)
