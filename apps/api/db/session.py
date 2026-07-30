"""异步 Engine 与 Session 工厂。

- 使用 asyncpg 驱动（postgresql+asyncpg://）。
- Session 工厂通过依赖注入使用；测试时替换 DATABASE_URL。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from apps.api.config import settings


def _build_async_url() -> str:
    """将 DATABASE_URL 转为 asyncpg 驱动格式。

    支持输入: postgresql+psycopg:// 或 postgresql://
    输出:     postgresql+asyncpg://
    """
    url = settings.database_url
    # 去掉已有的驱动前缀
    for prefix in ("+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    if "://" not in url:
        raise ValueError("Invalid DATABASE_URL")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


_engine = None
_sessionmaker = None


def _get_engine():
    """懒初始化 async Engine（单例）。

    测试环境（app_env == "test"）使用 NullPool，避免连接池跨事件循环复用。
    """
    global _engine
    if _engine is None:
        url = _build_async_url()
        if settings.app_env == "test":
            _engine = create_async_engine(
                url,
                echo=False,
                poolclass=NullPool,
            )
        else:
            _engine = create_async_engine(
                url,
                echo=False,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
    return _engine


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _sessionmaker


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI 依赖：提供一次请求使用的 AsyncSession。

    用法:
        from fastapi import Depends
        from apps.api.db.session import get_session

        @router.get("/example")
        async def example(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with _get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_engine():
    """获取 async Engine（供 Alembic 和测试使用）。"""
    return _get_engine()


async def dispose_engine() -> None:
    """释放全局 engine（测试隔离：在事件循环切换时重置连接池）。"""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def session_context() -> AsyncSession:
    """创建独立的 AsyncSession 上下文管理器（供 Worker 等非 FastAPI 场景使用）。

    用法:
        from apps.api.db.session import session_context

        async with session_context() as session:
            result = await session.execute(...)
    """
    return _get_sessionmaker()()
