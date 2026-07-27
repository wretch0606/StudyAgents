"""共享 SQLAlchemy 2.x DeclarativeBase。

API 和 Worker 中所有模型均继承自此 Base，确保 Alembic 可收集统一的 metadata。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类。"""

    pass


# ---- 公共工具函数 ----

def utcnow() -> datetime:
    """返回当前 UTC 时间（不含时区对象，数据库存 UTC naive）。"""
    return datetime.now(UTC).replace(tzinfo=None)


def new_uuid() -> uuid.UUID:
    """生成 UUID v4。"""
    return uuid.uuid4()


def pk():
    """UUID 主键列，默认生成 UUID v4。"""
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)


def created_at_col():
    """创建时间列（UTC），server_default=now()。"""
    return mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )


def updated_at_col():
    """更新时间列（UTC），自动更新。"""
    return mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
