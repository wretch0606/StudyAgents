"""Demo Cache — 模型不可用时的演示缓存模式。

仅在 DEMO_CACHE_MODE 环境变量显式设置时启用。默认实时模式。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def is_demo_mode() -> bool:
    """演示缓存模式是否启用（每次调用时读取环境变量）。"""
    return bool(os.getenv("DEMO_CACHE_MODE", ""))


class DemoCache:
    """基于内存的演示缓存。

    缓存键: (agent, prompt_version, input_hash, filters) 的 SHA-256
    缓存值: 公开 DTO（不含私有答案/评分点/Prompt/密钥）

    单例用法:
        cache = get_demo_cache()
        hit = cache.get(agent, prompt_version, messages, filters)
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def _make_key(
        self,
        agent: str,
        prompt_version: str,
        messages: list,
        filters: dict | None = None,
    ) -> str:
        raw = json.dumps({
            "agent": agent,
            "prompt_version": prompt_version,
            "messages": [
                {"role": m.get("role", ""), "content": m.get("content", "")}
                if isinstance(m, dict) else {
                    "role": getattr(m, "role", ""),
                    "content": getattr(m, "content", ""),
                }
                for m in messages
            ],
            "filters": filters or {},
        }, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(
        self,
        agent: str,
        prompt_version: str,
        messages: list,
        filters: dict | None = None,
    ) -> Any | None:
        """查询缓存。命中时返回公开 DTO 并附加 _demo=True 标记。未命中返回 None。"""
        key = self._make_key(agent, prompt_version, messages, filters)
        value = self._store.get(key)
        if value is not None:
            value["_demo"] = True
        return value

    def set(
        self,
        agent: str,
        prompt_version: str,
        messages: list,
        value: Any,
        filters: dict | None = None,
    ) -> None:
        """写入缓存。拒绝含私有字段的内容。"""
        if isinstance(value, dict):
            forbidden = {"expected_answer", "rubric", "private_answer",
                         "grade_private", "step_scores", "prompt", "api_key"}
            for k in forbidden:
                if k in value:
                    raise ValueError(f"缓存拒绝含私有字段: {k}")
        key = self._make_key(agent, prompt_version, messages, filters)
        self._store[key] = value

    def clear(self) -> None:
        """清空缓存。"""
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


# 模块级单例
_demo_cache: DemoCache | None = None


def get_demo_cache() -> DemoCache:
    global _demo_cache
    if _demo_cache is None:
        _demo_cache = DemoCache()
    return _demo_cache
