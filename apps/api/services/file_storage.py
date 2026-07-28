"""文件校验与存储服务 — Issue #11-2。

职责：扩展名/MIME/签名校验、流式 SHA-256、100 MB 限制、原子保存、SHA-256 去重。
不实现 HTTP 端点、任务执行或重试。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path

from apps.api.config import settings

# ---- 白名单 ----

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

MAGIC_SIGNATURES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",
    ".pptx": b"PK\x03\x04",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".png": b"\x89PNG\r\n\x1a\n",
}

MAX_SIZE_MB = 100
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024


# ---- 错误 ----

class FileValidationError(Exception):
    """文件校验失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---- 文件名清洗 ----

_DANGEROUS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_PATH_TRAVERSAL = re.compile(r'\.\.|%2e%2e|%252e', re.IGNORECASE)


def sanitize_filename(filename: str) -> str:
    """清洗危险字符，返回安全的文件名。"""
    name = _DANGEROUS_CHARS.sub("_", filename)
    name = _PATH_TRAVERSAL.sub("", name)
    name = name.strip(". ")
    if not name:
        name = "unnamed"
    return name[:255]


# ---- 文件校验 ----

def validate_extension(filename: str) -> str:
    """校验扩展名在白名单内，返回归一化的扩展名（小写）。"""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            "FILE_UNSUPPORTED_TYPE",
            f"不支持的文件类型: {ext}。允许: {', '.join(ALLOWED_EXTENSIONS.keys())}",
        )
    return ext


def validate_mime(declared_mime: str, ext: str) -> None:
    """校验声明的 MIME 与扩展名一致。"""
    expected = ALLOWED_EXTENSIONS.get(ext, "")
    if declared_mime and declared_mime != expected:
        raise FileValidationError(
            "FILE_UNSUPPORTED_TYPE",
            f"MIME 类型 {declared_mime} 与扩展名 {ext} 不一致，期望 {expected}",
        )


def validate_magic(header: bytes, ext: str) -> None:
    """校验文件头魔数。"""
    expected = MAGIC_SIGNATURES.get(ext, b"")
    if expected and not header.startswith(expected):
        raise FileValidationError(
            "FILE_UNSUPPORTED_TYPE",
            f"文件内容与扩展名 {ext} 不匹配",
        )


# ---- 流式读取 + SHA-256 ----

def _stream_and_hash(
    source, *, max_bytes: int = MAX_SIZE_BYTES,
) -> tuple[bytes, str, int]:
    """流式读取文件，计算 SHA-256，限制大小。返回 (header, sha256, total_bytes)。"""
    sha = hashlib.sha256()
    total = 0
    header = b""

    while True:
        chunk = source.read(8192)
        if not chunk:
            break
        if not header:
            header = chunk[:16]
        total += len(chunk)
        if total > max_bytes:
            raise FileValidationError(
                "FILE_TOO_LARGE",
                f"文件大小超过 {MAX_SIZE_MB} MB 上限",
            )
        sha.update(chunk)

    return header, sha.hexdigest(), total


# ---- 原子保存 ----

def save_file(source, *, filename: str) -> tuple[str, str, int]:
    """校验流 → 写入临时文件 → 原子移动到持久目录。

    返回 (file_path, sha256, size_bytes)。
    失败时清理临时文件。
    """
    files_dir = Path(settings.files_root)
    files_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()
    storage_name = f"{uuid.uuid4().hex}{ext}"
    tmp_path = files_dir / f".tmp_{storage_name}"
    final_path = files_dir / storage_name

    # 流式读取 + hash
    header, sha256, total = _stream_and_hash(source)

    # 写入临时文件
    try:
        source.seek(0)
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(source, f, length=8192)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    # 原子移动
    try:
        os.replace(tmp_path, final_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        if final_path.exists():
            final_path.unlink()
        raise

    return str(final_path), sha256, total


def resolve_storage_path(storage_name: str) -> Path:
    """将数据库中的存储文件名解析为受控目录下的绝对路径。"""
    if not storage_name or Path(storage_name).name != storage_name:
        raise FileValidationError("FILE_STORAGE_INVALID", "非法的存储文件名")

    files_dir = Path(settings.files_root).resolve()
    file_path = (files_dir / storage_name).resolve()
    if file_path.parent != files_dir:
        raise FileValidationError("FILE_STORAGE_INVALID", "存储路径越界")
    return file_path


def delete_stored_file(file_path: str | Path) -> None:
    """删除 save_file 创建的文件；拒绝删除存储目录之外的路径。"""
    files_dir = Path(settings.files_root).resolve()
    target = Path(file_path).resolve()
    if target.parent != files_dir:
        raise FileValidationError("FILE_STORAGE_INVALID", "拒绝删除存储目录之外的文件")
    target.unlink(missing_ok=True)


# ---- 去重 ----

async def check_duplicate(sha256: str, *, db_session) -> dict | None:
    """检查 SHA-256 是否已存在有效文档。返回已有文档信息或 None。"""
    from sqlalchemy import select

    from apps.api.db.models.document import Document

    result = await db_session.execute(
        select(Document).where(
            Document.sha256 == sha256,
            Document.status != "deleted",
        )
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        return None
    return {
        "document_id": str(existing.id),
        "name": existing.name,
        "sha256": existing.sha256,
        "status": existing.status,
    }
