"""ModelGateway — D 提供给 C 的统一大模型调用接口。

C 只传 Prompt/消息/Schema/参数；D 处理供应商、密钥、超时、重试、费用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Generic, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from apps.api.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ---- 常量 ----
CONNECT_TIMEOUT = 10.0
TOTAL_TIMEOUT = 25.0
MAX_RETRIES = 2
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
BASE_RETRY_DELAY = 0.8  # 秒


# ---- 数据模型 ----

class ModelMessage(BaseModel):
    role: str
    content: str


class ModelCallResult(BaseModel, Generic[T]):
    output: T
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_cny: float


class ModelGatewayError(Exception):
    """模型网关统一异常。"""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# ---- 费用估算 ----

# 默认价格（元/1K tokens），可通过配置覆盖
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.001, "output": 0.002},
    "deepseek-reasoner": {"input": 0.004, "output": 0.016},
    "gpt-4o": {"input": 0.015, "output": 0.060},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.00060},
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算费用。无价格数据时返回 -1.0 表示"费用未知"。"""
    prices = _DEFAULT_PRICES.get(model)
    if prices is None:
        return -1.0
    return (input_tokens / 1000) * prices["input"] + (output_tokens / 1000) * prices["output"]


# ---- Protocol ----

class ModelGateway(Protocol):
    """C 调用的统一模型接口协议。"""

    async def invoke_structured(
        self,
        *,
        run_id: str,
        trace_id: str,
        agent: str,
        prompt_version: str,
        messages: list[ModelMessage],
        output_schema: type[T],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ModelCallResult[T]:
        ...


# ---- OpenAI 兼容适配器 ----

class OpenAIAdapter:
    """通过 HTTP 调用 OpenAI 兼容 API 的适配器。

    支持 deepseek、gpt-4o 等兼容接口。
    provider / model / base_url / api_key 全部来自配置。
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str = "openai",
    ) -> None:
        self.base_url = (base_url or settings.model_base_url).rstrip("/")
        self.api_key = api_key or settings.model_api_key
        self.model = model or settings.model_text_name
        self.provider = provider

    async def invoke_structured(
        self,
        *,
        run_id: str,
        trace_id: str,
        agent: str,
        prompt_version: str,
        messages: list[ModelMessage],
        output_schema: type[T],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ModelCallResult[T]:
        """调用模型并返回结构化输出。包含重试、超时、JSON 修复。"""
        # 演示缓存模式
        from apps.api.services.demo_cache import get_demo_cache, is_demo_mode
        if is_demo_mode():
            cache = get_demo_cache()
            cached = cache.get(agent, prompt_version, messages)
            if cached is not None:
                logger.info(
                    "demo cache hit agent=%s prompt=%s", agent, prompt_version,
                )
                output = output_schema(**cached)
                return ModelCallResult(
                    output=output, provider="demo-cache", model="cached",
                    input_tokens=0, output_tokens=0, latency_ms=0,
                    estimated_cost_cny=0.0,
                )
            raise ModelGatewayError(
                "DEMO_CACHE_MISS",
                f"演示缓存未命中 (agent={agent}, prompt={prompt_version})。"
                "请先以实时模式运行并填充缓存。",
                retryable=False,
            )

        if not self.base_url or not self.api_key:
            raise ModelGatewayError(
                "MODEL_CONFIG_MISSING",
                "模型配置缺失：请设置 MODEL_BASE_URL 和 MODEL_API_KEY。",
                retryable=False,
            )

        body = self._build_body(messages, output_schema, temperature, max_tokens)
        last_error: Exception | None = None

        t0 = time.monotonic()
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = await self._send(body, trace_id, agent)
                result = self._parse_and_fix(raw, output_schema, trace_id)
                latency = int((time.monotonic() - t0) * 1000)

                usage = raw.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                cost = _estimate_cost(self.model, input_tokens, output_tokens)

                logger.info(
                    "model call ok: run_id=%s agent=%s model=%s provider=%s "
                    "tokens_in=%d tokens_out=%d latency_ms=%d cost=%.6f",
                    run_id, agent, self.model, self.provider,
                    input_tokens, output_tokens, latency, cost if cost >= 0 else -1,
                )
                # 填充演示缓存（实时模式成功后，缓存公开 DTO 供后续演示使用）
                try:
                    from apps.api.services.demo_cache import get_demo_cache
                    cache = get_demo_cache()
                    cache.set(agent, prompt_version, messages, result.model_dump())
                except Exception:
                    pass  # 缓存写入失败不影响主流程
                return ModelCallResult(
                    output=result,
                    provider=self.provider,
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency,
                    estimated_cost_cny=cost if cost >= 0 else -1.0,
                )

            except ModelGatewayError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES and self._is_retryable(exc):
                    delay = BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "model call retry %d/%d after %.1fs: run_id=%s agent=%s err=%s",
                        attempt + 1, MAX_RETRIES, delay, run_id, agent, exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                break

        logger.error(
            "model call failed after %d attempts: run_id=%s agent=%s err=%s",
            MAX_RETRIES + 1, run_id, agent, last_error,
        )
        raise ModelGatewayError(
            "AGENT_MODEL_TIMEOUT",
            "模型服务暂时未响应，请稍后重试。",
            retryable=True,
        )

    def _build_body(
        self,
        messages: list[ModelMessage],
        output_schema: type[T],
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_schema.__name__,
                    "schema": output_schema.model_json_schema(),
                },
            },
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        return body

    async def _send(self, body: dict[str, Any], trace_id: str, agent: str) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # 日志中脱敏 API Key
        safe_headers = {**headers, "Authorization": "Bearer ***"}
        logger.debug("POST %s headers=%s body_model=%s", url, safe_headers, body.get("model"))

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT),
        ) as client:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                self._raise_for_status(resp.status_code, resp.text)
            return resp.json()

    def _parse_and_fix(
        self, raw: dict[str, Any], output_schema: type[T], trace_id: str,
    ) -> T:
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise ModelGatewayError(
                "AGENT_OUTPUT_INVALID",
                "模型返回了空响应。",
                retryable=True,
            )

        # 尝试直接解析
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # JSON 修复：尝试提取 JSON 块
            fixed = _try_repair_json(content)
            if fixed is None:
                raise ModelGatewayError(
                    "AGENT_OUTPUT_INVALID",
                    "模型返回的内容不是有效 JSON，且修复失败。",
                    retryable=True,
                )
            data = fixed

        try:
            return output_schema.model_validate(data)
        except Exception as exc:
            raise ModelGatewayError(
                "AGENT_OUTPUT_INVALID",
                f"模型输出不符合预期 Schema: {exc}",
                retryable=True,
            ) from exc

    def _raise_for_status(self, status_code: int, body: str) -> None:
        if status_code == 429:
            raise ModelGatewayError(
                "AGENT_MODEL_RATE_LIMITED", "模型服务限流，请稍后重试。", retryable=True,
            )
        if status_code in (500, 502, 503, 504):
            raise ModelGatewayError(
                "AGENT_MODEL_TIMEOUT", "模型服务暂时不可用。", retryable=True,
            )
        raise ModelGatewayError(
            f"MODEL_HTTP_{status_code}",
            f"模型服务返回 HTTP {status_code}。",
            retryable=False,
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, ModelGatewayError):
            return exc.retryable
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.NetworkError):
            return True
        return False


# ---- JSON 修复 ----

def _try_repair_json(text: str) -> dict[str, Any] | None:
    """尝试从非标准 JSON 文本中提取有效 JSON 对象。

    仅修复最简单的场景：模型在 JSON 前后附加了 markdown 代码块或多余文本。
    """
    # 尝试提取 ```json ... ``` 代码块
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个 { ... } 块
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ---- Fake Adapter（测试用） ----

class FakeAdapter:
    """测试用假适配器 — 返回预定义的结构化输出。

    仅用于测试；不得在生产代码中静默使用。
    """

    def __init__(self, responses: list[BaseModel] | None = None) -> None:
        self.responses = responses or []
        self.call_count = 0
        self.last_call: dict[str, Any] | None = None

    async def invoke_structured(
        self,
        *,
        run_id: str,
        trace_id: str,
        agent: str,
        prompt_version: str,
        messages: list[ModelMessage],
        output_schema: type[T],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ModelCallResult[T]:
        # 演示缓存模式（与 OpenAIAdapter 行为一致）
        from apps.api.services.demo_cache import get_demo_cache, is_demo_mode
        if is_demo_mode():
            cache = get_demo_cache()
            cached = cache.get(agent, prompt_version, messages)
            if cached is not None:
                output = output_schema(**cached)
                return ModelCallResult(
                    output=output, provider="demo-cache", model="cached",
                    input_tokens=0, output_tokens=0, latency_ms=0,
                    estimated_cost_cny=0.0,
                )
            raise ModelGatewayError(
                "DEMO_CACHE_MISS",
                f"演示缓存未命中 (agent={agent}, prompt={prompt_version})。",
                retryable=False,
            )

        self.call_count += 1
        self.last_call = {
            "run_id": run_id, "agent": agent, "prompt_version": prompt_version,
            "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
        }
        if self.call_count > len(self.responses):
            raise ModelGatewayError(
                "FAKE_NO_RESPONSE",
                f"FakeAdapter 响应不足: {self.call_count} > {len(self.responses)}",
                retryable=False,
            )
        output = self.responses[self.call_count - 1]
        if not isinstance(output, output_schema):
            raise ModelGatewayError(
                "FAKE_TYPE_MISMATCH",
                f"FakeAdapter 类型不匹配: {type(output).__name__} != {output_schema.__name__}",
                retryable=False,
            )
        return ModelCallResult(
            output=output,
            provider="fake",
            model="fake-model",
            input_tokens=10,
            output_tokens=20,
            latency_ms=5,
            estimated_cost_cny=0.0,
        )
