"""初始化五个预置本地账号。

首次部署运行：
    uv run python scripts/init_users.py

默认密码通过环境变量 INIT_DEFAULT_PASSWORD 传入。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.config import settings
from apps.api.db.models.user import User
from apps.api.services.auth import hash_password


def _build_async_url() -> str:
    url = settings.database_url
    for prefix in ("+psycopg_async", "+psycopg", "+asyncpg"):
        url = url.replace(prefix, "")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


PRESET_USERS = [
    {"username": "admin",     "display_name": "管理员",   "role": "admin"},
    {"username": "member_a",  "display_name": "成员 A",   "role": "member"},
    {"username": "member_b",  "display_name": "成员 B",   "role": "member"},
    {"username": "member_c",  "display_name": "成员 C",   "role": "member"},
    {"username": "member_d",  "display_name": "成员 D",   "role": "member"},
]


async def main() -> None:
    default_pw = os.getenv("INIT_DEFAULT_PASSWORD", "").strip()
    if not default_pw:
        print("错误：请设置 INIT_DEFAULT_PASSWORD 环境变量。")
        print("  PowerShell: $env:INIT_DEFAULT_PASSWORD = 'your-secure-password'")
        print("首次部署后请立即修改默认密码。")
        sys.exit(1)

    if not settings.database_url:
        print("错误：DATABASE_URL 未配置。")
        sys.exit(1)

    url = _build_async_url()
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        for entry in PRESET_USERS:
            existing = await session.execute(
                select(User).where(User.username == entry["username"])
            )
            if existing.scalar_one_or_none():
                print(f"  跳过（已存在）: {entry['username']}")
                continue

            user = User(
                username=entry["username"],
                display_name=entry["display_name"],
                password_hash=hash_password(default_pw),
                role=entry["role"],
                is_active=True,
            )
            session.add(user)
            print(f"  创建用户: {entry['username']} ({entry['role']})")

        await session.commit()

    await engine.dispose()
    print(f"\n完成。已创建/更新 {len(PRESET_USERS)} 个预置账号。")
    print("请提醒所有用户首次登录后修改密码。")


if __name__ == "__main__":
    asyncio.run(main())
