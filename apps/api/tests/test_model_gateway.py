"""ModelGateway 测试 — 不使用真实付费模型。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from apps.api.services.model_gateway import (  # noqa: E402
    FakeAdapter,
    ModelGatewayError,
    ModelMessage,
    _try_repair_json,
)

# ---- 测试用 Schema ----

class TestOutput(BaseModel):
    answer: str
    confidence: float


class AltOutput(BaseModel):
    name: str
    count: int


# ---- 结构化输出 ----

@pytest.mark.asyncio
async def test_fake_adapter_structured_output() -> None:
    """FakeAdapter 正确返回结构化输出。"""
    adapter = FakeAdapter(responses=[TestOutput(answer="hello", confidence=0.9)])
    result = await adapter.invoke_structured(
        run_id="r1", trace_id="t1", agent="test",
        prompt_version="v1", messages=[ModelMessage(role="user", content="hi")],
        output_schema=TestOutput,
    )
    assert result.output.answer == "hello"
    assert result.output.confidence == 0.9
    assert result.provider == "fake"
    assert result.input_tokens == 10
    assert result.output_tokens == 20
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_fake_adapter_records_call() -> None:
    """FakeAdapter 记录每次调用参数。"""
    adapter = FakeAdapter(responses=[TestOutput(answer="ok", confidence=1.0)])
    messages = [ModelMessage(role="user", content="test")]
    await adapter.invoke_structured(
        run_id="rx", trace_id="tx", agent="qa", prompt_version="v2",
        messages=messages, output_schema=TestOutput, temperature=0.5,
        max_tokens=100,
    )
    assert adapter.call_count == 1
    assert adapter.last_call is not None
    assert adapter.last_call["run_id"] == "rx"
    assert adapter.last_call["agent"] == "qa"
    assert adapter.last_call["temperature"] == 0.5
    assert adapter.last_call["max_tokens"] == 100


# ---- JSON 修复 ----

def test_repair_json_code_block() -> None:
    """从 markdown 代码块中提取 JSON。"""
    text = '```json\n{"answer": "ok", "confidence": 0.8}\n```'
    result = _try_repair_json(text)
    assert result == {"answer": "ok", "confidence": 0.8}


def test_repair_json_bare_object() -> None:
    """从多余文本中提取 JSON 对象。"""
    text = 'Some prefix text {"answer": "yes", "confidence": 0.5} trailing text'
    result = _try_repair_json(text)
    assert result == {"answer": "yes", "confidence": 0.5}


def test_repair_json_invalid_returns_none() -> None:
    """无效 JSON 返回 None（不抛异常）。"""
    assert _try_repair_json("not json at all") is None
    assert _try_repair_json("{invalid") is None


# ---- 泛型行为 ----

@pytest.mark.asyncio
async def test_fake_adapter_different_schemas() -> None:
    """FakeAdapter 支持不同的 output_schema 类型。"""
    adapter = FakeAdapter(responses=[AltOutput(name="test", count=42)])
    result = await adapter.invoke_structured(
        run_id="r2", trace_id="t2", agent="test",
        prompt_version="v1", messages=[ModelMessage(role="user", content="x")],
        output_schema=AltOutput,
    )
    assert result.output.name == "test"
    assert result.output.count == 42


# ---- 配置缺失 ----

@pytest.mark.asyncio
async def test_openai_adapter_missing_config() -> None:
    """当配置缺失时抛出 MODEL_CONFIG_MISSING。"""
    from apps.api.services.model_gateway import OpenAIAdapter

    # 隔离 .env 中的真实 API key：临时覆盖 settings 值
    import apps.api.config as _cfg
    old_base = _cfg.settings.model_base_url
    old_key = _cfg.settings.model_api_key
    _cfg.settings.model_base_url = ""
    _cfg.settings.model_api_key = ""
    try:
        adapter = OpenAIAdapter(base_url="", api_key="", model="")
        with pytest.raises(ModelGatewayError) as exc_info:
            await adapter.invoke_structured(
                run_id="r3", trace_id="t3", agent="test",
                prompt_version="v1", messages=[ModelMessage(role="user", content="x")],
                output_schema=TestOutput,
            )
        assert exc_info.value.code == "MODEL_CONFIG_MISSING"
        assert exc_info.value.retryable is False
    finally:
        _cfg.settings.model_base_url = old_base
        _cfg.settings.model_api_key = old_key


# ---- 费用估算 ----

def test_estimate_cost_known_model() -> None:
    """已知模型返回合理费用。"""
    from apps.api.services.model_gateway import _estimate_cost

    cost = _estimate_cost("deepseek-chat", 1000, 500)
    assert cost >= 0
    assert cost == pytest.approx(0.001 * 1 + 0.002 * 0.5, rel=0.01)


def test_estimate_cost_unknown_model() -> None:
    """未知模型返回 -1.0（费用未知）。"""
    from apps.api.services.model_gateway import _estimate_cost

    assert _estimate_cost("unknown-model-xyz", 1000, 500) == -1.0


# ---- 日志脱敏 ----

def test_model_message_serialization() -> None:
    """ModelMessage 序列化不包含额外敏感字段。"""
    m = ModelMessage(role="user", content="hello")
    d = m.model_dump()
    assert d == {"role": "user", "content": "hello"}
    assert "api_key" not in d
    assert "token" not in d


# ---- 重试逻辑 ----

@pytest.mark.asyncio
async def test_fake_adapter_runs_out_of_responses() -> None:
    """FakeAdapter 响应用尽时抛出异常。"""
    adapter = FakeAdapter(responses=[TestOutput(answer="only", confidence=0.5)])
    await adapter.invoke_structured(
        run_id="r1", trace_id="t1", agent="t",
        prompt_version="v1", messages=[ModelMessage(role="user", content="a")],
        output_schema=TestOutput,
    )
    with pytest.raises(ModelGatewayError) as exc_info:
        await adapter.invoke_structured(
            run_id="r1", trace_id="t1", agent="t",
            prompt_version="v1", messages=[ModelMessage(role="user", content="b")],
            output_schema=TestOutput,
        )
    assert "FAKE_NO_RESPONSE" in exc_info.value.code


# ---- 超时仿真 ----

@pytest.mark.asyncio
async def test_retryable_error_identification() -> None:
    """验证 retryable 错误判断。"""
    import httpx

    from apps.api.services.model_gateway import OpenAIAdapter

    adapter = OpenAIAdapter(base_url="http://x", api_key="k", model="m")

    # 429 应可重试
    exc_429 = ModelGatewayError("AGENT_MODEL_RATE_LIMITED", "", retryable=True)
    assert adapter._is_retryable(exc_429) is True

    # 配置缺失不可重试
    exc_cfg = ModelGatewayError("MODEL_CONFIG_MISSING", "", retryable=False)
    assert adapter._is_retryable(exc_cfg) is False

    # httpx.TimeoutException 应可重试
    assert adapter._is_retryable(httpx.TimeoutException("timeout")) is True

    # httpx.NetworkError 应可重试
    assert adapter._is_retryable(httpx.NetworkError("network")) is True
