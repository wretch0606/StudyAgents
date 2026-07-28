#!/usr/bin/env python3
"""StudyAgents 数据库与原文件备份工具。

用法:
  uv run python scripts/backup.py                    # 备份到 ./backups/
  uv run python scripts/backup.py --output /mnt/nas  # 指定输出目录

产物:
  backup_<timestamp>_<git_hash>.tar.gz       # 完整备份包
  backup_<timestamp>_<git_hash>.sha256       # SHA-256 校验文件

策略:
  - PostgreSQL 业务数据 + 迁移版本：pg_dump --format=custom
  - 原始文件卷：打包 files_data 目录
  - 索引/向量数据不备份（可通过重跑 ingestion pipeline 重建）
  - 产物不写入 Git
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=8", "HEAD"], text=True,
        ).strip()
    except Exception:
        return "unknown"


def _ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def backup_db(output_dir: Path, timestamp: str) -> Path:
    """导出 PostgreSQL 业务数据（含迁移版本）。"""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 未设置，无法备份数据库")

    dump_path = output_dir / f"db_dump_{timestamp}.pgdump"
    env = os.environ.copy()
    env["PGPASSWORD"] = _extract_password(db_url)
    host = _extract_host(db_url)
    port = _extract_port(db_url)
    user = _extract_user(db_url)
    dbname = _extract_dbname(db_url)

    _run([
        "pg_dump",
        "--host", host,
        "--port", port,
        "--username", user,
        "--dbname", dbname,
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--file", str(dump_path),
    ], env=env)
    return dump_path


def backup_files(file_root: str, output_dir: Path, timestamp: str) -> Path:
    """打包原始文件卷（排除临时文件和页面图片缓存）。"""
    files_dir = Path(file_root)
    if not files_dir.exists():
        print(f"  警告: FILES_ROOT={file_root} 不存在，跳过文件备份")
        return None

    archive_path = output_dir / f"files_{timestamp}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        for entry in sorted(files_dir.rglob("*")):
            if entry.is_file():
                # 排除临时文件和页面图片（可重建）
                if entry.name.startswith(".tmp_"):
                    continue
                arcname = str(entry.relative_to(files_dir))
                tar.add(entry, arcname=arcname)
    return archive_path


def checksum_file(path: Path) -> str:
    """计算文件 SHA-256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_password(url: str) -> str:
    # postgresql+psycopg://user:pass@host:port/db
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
    parser = argparse.ArgumentParser(description="StudyAgents 备份工具")
    parser.add_argument("--output", default="./backups", help="备份输出目录（默认 ./backups/）")
    parser.add_argument("--files-root", default=None, help="文件卷路径（默认 $FILES_ROOT）")
    args = parser.parse_args()

    output_dir = Path(args.output)
    _ensure_output_dir(output_dir)

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    git_ref = _git_hash()
    label = f"backup_{ts}_{git_ref}"

    print(f"=== StudyAgents 备份 {label} ===")

    # 1. 数据库
    print("\n[1/3] 备份 PostgreSQL...")
    db_dump = backup_db(output_dir, ts)

    # 2. 文件卷
    files_root = args.files_root or os.getenv("FILES_ROOT", "/data/files")
    print(f"\n[2/3] 备份文件卷 (FILES_ROOT={files_root})...")
    files_archive = backup_files(files_root, output_dir, ts)

    # 3. 打包 + 校验
    print("\n[3/3] 打包并校验...")
    bundle_path = output_dir / f"{label}.tar.gz"
    with tarfile.open(bundle_path, "w:gz") as tar:
        tar.add(db_dump, arcname=db_dump.name)
        if files_archive:
            tar.add(files_archive, arcname=files_archive.name)

    sha = checksum_file(bundle_path)
    checksum_path = output_dir / f"{label}.sha256"
    checksum_path.write_text(f"{sha}  {bundle_path.name}\n")

    # 清理中间文件
    db_dump.unlink()
    if files_archive:
        files_archive.unlink()

    print("\n备份完成:")
    print(f"  {bundle_path} ({bundle_path.stat().st_size} bytes)")
    print(f"  {checksum_path}")
    print(f"  SHA-256: {sha}")
    print(
        "\n索引/向量数据策略: 不备份"
        "（可通过 docker compose exec worker 重跑 pipeline 重建）"
    )


if __name__ == "__main__":
    main()
