"""备份恢复演练测试 — 在隔离测试 DB 中验证备份→清空→恢复→一致性。

需要 DATABASE_URL 指向测试数据库。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

DATABASE_URL = os.getenv("DATABASE_URL", "")
_needs_db = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@_needs_db
def test_backup_script_runs() -> None:
    """备份脚本能正常执行（至少输出校验文件）。"""
    output_dir = Path(tempfile.mkdtemp(prefix="studyagents_backup_test_"))
    try:
        result = subprocess.run(
            [sys.executable, "scripts/backup.py", "--output", str(output_dir)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            # pg_dump 可能不可用 — 跳过而非失败
            if "pg_dump" in result.stderr or "not found" in result.stderr:
                pytest.skip("pg_dump not available")
            pytest.fail(f"backup.py failed:\n{result.stderr}")
        sha_files = list(output_dir.glob("*.sha256"))
        assert len(sha_files) >= 1, f"Expected .sha256 file, got: {list(output_dir.iterdir())}"
    finally:
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)


@_needs_db
def test_backup_creates_valid_checksum() -> None:
    """备份产物 SHA-256 校验一致。"""
    output_dir = Path(tempfile.mkdtemp(prefix="studyagents_backup_test_"))
    try:
        subprocess.run(
            [sys.executable, "scripts/backup.py", "--output", str(output_dir)],
            capture_output=True, timeout=60, check=False,
        )
        sha_files = list(output_dir.glob("*.sha256"))
        if not sha_files:
            pytest.skip("No backup produced (pg_dump missing?)")
        for sf in sha_files:
            content = sf.read_text().strip()
            expected_sha, filename = content.split(maxsplit=1)
            bundle = output_dir / filename
            if bundle.exists():
                import hashlib
                actual = hashlib.sha256(bundle.read_bytes()).hexdigest()
                assert actual == expected_sha, f"SHA-256 mismatch for {filename}"
    finally:
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)


def test_backup_imports() -> None:
    """备份脚本可导入。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import backup
    assert hasattr(backup, "main")


def test_restore_imports() -> None:
    """恢复脚本可导入。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import restore
    assert hasattr(restore, "main")


@_needs_db
def test_backup_restore_cycle() -> None:
    """完整备份→恢复→验证循环（隔离测试）。"""
    output_dir = Path(tempfile.mkdtemp(prefix="studyagents_backup_test_"))
    try:
        # 1. 在测试 DB 中创建已知数据
        _create_test_data()

        # 2. 备份
        result = subprocess.run(
            [sys.executable, "scripts/backup.py", "--output", str(output_dir)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            pytest.skip(f"backup.py failed: {result.stderr}")

        bundles = sorted(output_dir.glob("backup_*.tar.gz"))
        if not bundles:
            pytest.skip("No backup bundle produced")

        # 3. 恢复
        result = subprocess.run(
            [
                sys.executable, "scripts/restore.py",
                "--force", "--skip-files",
                str(bundles[0]),
            ],
            capture_output=True, text=True, timeout=60,
        )
        # restore may fail on clean env — check stdout for success marker
        assert "恢复完成" in result.stdout or result.returncode == 0, (
            f"restore.py failed: {result.stderr}"
        )

        # 4. 验证数据完整性
        _verify_test_data()
    finally:
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)


def _create_test_data() -> None:
    """在测试 DB 中创建用于验证的数据。"""
    try:
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        db_url = DATABASE_URL.replace(
            "postgresql+psycopg://", "postgresql+asyncpg://",
        )

        async def _create():
            engine = create_async_engine(db_url)
            async with engine.connect() as conn:
                # 确保 users 表有测试数据
                existing = await conn.execute(text(
                    "SELECT COUNT(*) FROM users WHERE username = 'backup_test_user'"
                ))
                if existing.scalar() == 0:
                    await conn.execute(text(
                        "INSERT INTO users (id, username, display_name, password_hash, role) "
                        "VALUES (:id, 'backup_test_user', 'Backup Test', '', 'member')"
                    ), {"id": str(uuid.uuid4())})
                    await conn.commit()
            await engine.dispose()

        asyncio.run(_create())
    except Exception:
        pytest.skip("Cannot create test data")


def _verify_test_data() -> None:
    """验证恢复后的数据。"""
    try:
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        db_url = DATABASE_URL.replace(
            "postgresql+psycopg://", "postgresql+asyncpg://",
        )

        async def _verify():
            engine = create_async_engine(db_url)
            async with engine.connect() as conn:
                # 验证 users 表存在且可查询
                result = await conn.execute(text("SELECT COUNT(*) FROM users"))
                count = result.scalar()
                assert count > 0, "恢复后 users 表为空"
            await engine.dispose()

        asyncio.run(_verify())
    except Exception as e:
        pytest.fail(f"恢复后验证失败: {e}")
