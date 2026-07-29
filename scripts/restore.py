#!/usr/bin/env python3
"""StudyAgents 数据库与原文件恢复工具。

用法:
  uv run python scripts/restore.py backup_20260728_120000_abc12345.tar.gz
  uv run python scripts/restore.py --force backup_20260728_120000_abc12345.tar.gz

恢复流程:
  1. 校验备份文件完整性（SHA-256）
  2. 确认目标环境
  3. 恢复 PostgreSQL
  4. 恢复文件卷
  5. 运行迁移兼容检查
  6. 引用一致性验证

默认安全策略: 恢复前需要人工确认（--force 跳过）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def _prompt_confirm(msg: str, force: bool) -> bool:
    if force:
        return True
    print(f"\n⚠️  {msg}")
    resp = input("  确认继续? [y/N] ").strip().lower()
    return resp == "y"


def verify_bundle(bundle_path: Path) -> bool:
    """校验备份包 SHA-256。"""
    checksum_path = Path(str(bundle_path) + ".sha256")  # same name + .sha256
    # 也尝试 backup_<ts>_<hash>.sha256
    parent = bundle_path.parent
    stem = bundle_path.name.replace(".tar.gz", "")
    alt_checksum = parent / f"{stem}.sha256"

    for ck in [checksum_path, alt_checksum]:
        if ck.exists():
            expected = ck.read_text().split()[0]
            actual = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
            if expected == actual:
                print(f"  ✅ SHA-256 校验通过: {expected[:16]}...")
                return True
            else:
                print("  ❌ SHA-256 校验失败")
                print(f"     期望: {expected[:16]}...")
                print(f"     实际: {actual[:16]}...")
                return False

    print("  ⚠️  未找到校验文件，跳过 SHA-256 校验")
    return True  # 无校验文件时允许继续


def restore_db(dump_path: Path, force: bool) -> None:
    """恢复 PostgreSQL。"""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 未设置，无法恢复数据库")

    if not _prompt_confirm(
        f"即将覆盖数据库 {_extract_dbname(db_url)}@{_extract_host(db_url)}",
        force,
    ):
        print("已取消。")
        sys.exit(0)

    env = os.environ.copy()
    env["PGPASSWORD"] = _extract_password(db_url)

    # 先断开现有连接
    subprocess.run([
        "psql",
        "--host", _extract_host(db_url),
        "--port", _extract_port(db_url),
        "--username", _extract_user(db_url),
        "--dbname", _extract_dbname(db_url),
        "-c", "SELECT pg_terminate_backend(pg_stat_activity.pid) "
              "FROM pg_stat_activity "
              "WHERE pg_stat_activity.datname = current_database() "
              "AND pid <> pg_backend_pid();",
    ], env=env, check=False)

    _run([
        "pg_restore",
        "--host", _extract_host(db_url),
        "--port", _extract_port(db_url),
        "--username", _extract_user(db_url),
        "--dbname", _extract_dbname(db_url),
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-acl",
        str(dump_path),
    ], env=env)


def restore_files(archive_path: Path, target_root: str, force: bool) -> None:
    """恢复文件卷。"""
    if not _prompt_confirm(f"即将恢复文件到 {target_root}", force):
        print("已跳过文件恢复。")
        return

    target = Path(target_root)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=target)
    print(f"  ✅ 文件已恢复到 {target}")


def check_migration() -> None:
    """运行迁移兼容检查。"""
    print("\n[迁移兼容检查]")
    _run(["alembic", "current"])
    _run(["alembic", "upgrade", "head"])
    print("  ✅ 迁移兼容")


def check_references() -> None:
    """引用一致性检查（document ID ↔ SourceRef）。"""
    print("\n[引用一致性检查]")
    try:
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        db_url = os.getenv("DATABASE_URL", "")
        async_url = db_url.replace(
            "postgresql+psycopg://", "postgresql+asyncpg://",
        )

        async def _check():
            engine = create_async_engine(async_url)
            async with engine.connect() as conn:
                # 检查 agent_events.source_refs 中的 document_id 是否存在于 documents 表
                result = await conn.execute(text(
                    "SELECT ae.id, sr->>'document_id' AS doc_id "
                    "FROM agent_events ae, "
                    "jsonb_array_elements(ae.source_refs) sr "
                    "WHERE sr->>'document_id' NOT IN "
                    "(SELECT id::text FROM documents) "
                    "LIMIT 5"
                ))
                orphans = result.fetchall()
                if orphans:
                    print(f"  ⚠️  发现 {len(orphans)} 个悬空 SourceRef 引用")
                else:
                    print("  ✅ 所有 document_id 引用一致")
            await engine.dispose()

        asyncio.run(_check())
    except Exception as e:
        print(f"  ⚠️  引用检查跳过: {e}")


def _extract_password(url: str) -> str:
    at_pos = url.rfind("@")
    colon_pos = url.rfind(":", 0, at_pos)
    return url[colon_pos + 1:at_pos] if colon_pos > 0 else ""


def _extract_host(url: str) -> str:
    at_pos = url.rfind("@")
    slash_pos = url.find("/", at_pos)
    colon_pos = url.rfind(":", at_pos, slash_pos) if slash_pos > 0 else -1
    start = at_pos + 1 if at_pos > 0 else url.find("://") + 3
    end = colon_pos if colon_pos > 0 else (slash_pos if slash_pos > 0 else len(url))
    return url[start:end]


def _extract_port(url: str) -> str:
    at_pos = url.rfind("@")
    slash_pos = url.find("/", at_pos)
    colon_pos = url.rfind(":", at_pos, slash_pos) if slash_pos > 0 else -1
    if colon_pos > 0:
        return url[colon_pos + 1:slash_pos] if slash_pos > 0 else url[colon_pos + 1:]
    return "5432"


def _extract_user(url: str) -> str:
    proto_end = url.find("://") + 3
    colon_pos = url.find(":", proto_end)
    return url[proto_end:colon_pos]


def _extract_dbname(url: str) -> str:
    last_slash = url.rfind("/")
    query_pos = url.find("?", last_slash)
    if query_pos > 0:
        return url[last_slash + 1:query_pos]
    return url[last_slash + 1:]


def main() -> None:
    parser = argparse.ArgumentParser(description="StudyAgents 恢复工具")
    parser.add_argument("bundle", help="备份包路径 (*.tar.gz)")
    parser.add_argument("--force", action="store_true", help="跳过确认提示")
    parser.add_argument("--files-root", default=None, help="文件卷恢复目标（默认 $FILES_ROOT）")
    parser.add_argument("--skip-files", action="store_true", help="跳过文件卷恢复")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"❌ 备份文件不存在: {bundle_path}")
        sys.exit(1)

    print(f"=== StudyAgents 恢复 {bundle_path.name} ===")

    # 1. 校验
    print("\n[1/4] 校验备份完整性...")
    if not verify_bundle(bundle_path):
        sys.exit(1)

    # 2. 解包
    print("\n[2/4] 解包...")
    tmpdir = tempfile.mkdtemp(prefix="studyagents_restore_")
    with tarfile.open(bundle_path, "r:gz") as tar:
        tar.extractall(path=tmpdir)

    tmp = Path(tmpdir)
    db_dumps = sorted(tmp.glob("db_dump_*.pgdump"))
    file_archives = sorted(tmp.glob("files_*.tar.gz"))

    # 3. 恢复
    print("\n[3/4] 恢复...")
    if db_dumps:
        restore_db(db_dumps[0], args.force)
    else:
        print("  ⚠️  未找到数据库备份")

    if not args.skip_files and file_archives:
        files_root = args.files_root or os.getenv("FILES_ROOT", "/data/files")
        restore_files(file_archives[0], files_root, args.force)

    # 4. 验证
    print("\n[4/4] 恢复后验证...")
    check_migration()
    check_references()

    # 清理
    shutil.rmtree(tmpdir)
    print("\n✅ 恢复完成")


if __name__ == "__main__":
    main()
