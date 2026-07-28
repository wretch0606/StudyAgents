"""数据库集成测试 — 验证 pgvector 扩展可用。

需要运行中的 PostgreSQL + pgvector。
通过环境变量 DATABASE_URL 连接；未配置时跳过。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")


@pytest.fixture
def native_url() -> str:
    """psycopg 原生连接 URI。"""
    return DATABASE_URL.replace("+psycopg", "")


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set — skipped integration test")
def test_can_connect_to_postgres(native_url: str) -> None:
    """验证可以通过 psycopg 连接 PostgreSQL。"""
    import psycopg

    conn = psycopg.connect(native_url, autocommit=True, connect_timeout=5)
    try:
        cur = conn.execute("SELECT 1 AS ok")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1
    finally:
        conn.close()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set — skipped integration test")
def test_pgvector_extension_available(native_url: str) -> None:
    """验证 pgvector 扩展已安装。"""
    import psycopg

    conn = psycopg.connect(native_url, autocommit=True, connect_timeout=5)
    try:
        cur = conn.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        )
        row = cur.fetchone()
        assert row is not None, "pgvector extension is not installed"
        assert row[0] == "vector"
    finally:
        conn.close()
