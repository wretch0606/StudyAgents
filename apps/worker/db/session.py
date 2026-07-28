"""
数据库会话管理

提供异步 SQLAlchemy 引擎和会话工厂。
由 D（后端）负责维护 Alembic 迁移，B 在此使用已有表结构。
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.worker.config import ASYNC_DATABASE_URL, DEBUG

# 异步引擎
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=DEBUG,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
)

# 会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


from collections.abc import AsyncGenerator


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话（FastAPI 依赖注入 / Worker 手动使用）"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
