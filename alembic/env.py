"""Alembic 异步迁移环境。

- 从环境变量 DATABASE_URL 读取数据库连接。
- 自动加载 apps.api.db.models 中全部模型的 metadata。
- 支持 offline（生成 SQL）和 online（直接执行）两种模式。
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# 确保项目根在 path 中
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Alembic Config 对象
config = context.config

# 日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---- 加载全部模型 metadata ----
# 必须在此处导入 models 包，使 Base.metadata 包含所有表定义
import apps.api.db.models  # noqa: E402, F401 — 注册所有模型
from apps.api.db.base import Base  # noqa: E402

target_metadata = Base.metadata

# ---- 数据库 URL ----
# 优先使用环境变量；次选 alembic.ini 中的 sqlalchemy.url
_DB_URL = os.getenv("DATABASE_URL", "")

if _DB_URL:
    # 转换为 asyncpg 驱动格式
    for prefix in ("+psycopg_async", "+psycopg", "+asyncpg"):
        _DB_URL = _DB_URL.replace(prefix, "")
    _DB_URL = _DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

config.set_main_option("sqlalchemy.url", _DB_URL)


def run_migrations_offline() -> None:
    """Offline 模式 — 输出 SQL 脚本而不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """在给定连接上执行迁移。"""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Online 模式 — 使用异步引擎连接数据库并执行迁移。"""
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_async_engine(url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
