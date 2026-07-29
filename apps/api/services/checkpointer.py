"""LangGraph Checkpointer — D 负责创建和管理，供 C 编译状态图时使用。

用法（C 在 agents/graph.py 中）:
    from apps.api.services.checkpointer import get_checkpointer

    graph = build_qa_graph().compile(checkpointer=get_checkpointer())

开发环境使用 MemorySaver（内存）；生产环境可切换为 PostgresSaver。
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_checkpointer: MemorySaver | None = None


def init_checkpointer() -> MemorySaver:
    """初始化 checkpointer 单例（应用启动时调用）。"""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
        logger.info("LangGraph checkpointer initialized: MemorySaver")
    return _checkpointer


def get_checkpointer() -> MemorySaver:
    """获取 checkpointer 实例。

    若未初始化则自动创建（延迟初始化，兼容测试环境）。
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
        logger.info("LangGraph checkpointer auto-initialized: MemorySaver")
    return _checkpointer


async def dispose_checkpointer() -> None:
    """释放 checkpointer 资源（应用关闭时调用）。"""
    global _checkpointer
    _checkpointer = None
    logger.info("LangGraph checkpointer disposed")
