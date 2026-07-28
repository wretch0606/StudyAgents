"""
文件校验模块

负责：扩展名 → MIME → magic bytes → 大小 → SHA-256 → 去重
"""

import hashlib
import os
from pathlib import Path

from apps.worker.schemas import (
    ALLOWED_EXTENSIONS,
    DEFAULT_MAX_UPLOAD_MB,
    MAGIC_SIGNATURES,
    ValidationResult,
)


# ---- 文件头读取 ----

def _read_magic(file_path: str, length: int = 8) -> bytes:
    """读取文件头 magic bytes"""
    with open(file_path, "rb") as f:
        return f.read(length)


def _get_extension(filename: str) -> str:
    """获取小写扩展名"""
    return Path(filename).suffix.lower()


# ---- 各校验步骤 ----

def validate_extension(filename: str) -> tuple[bool, str]:
    """
    校验扩展名是否在允许列表中。
    返回 (合法, 错误码)。
    """
    ext = _get_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        return False, "FILE_UNSUPPORTED_TYPE"
    return True, ""


def validate_mime(file_path: str, filename: str) -> tuple[bool, str]:
    """
    校验文件头 magic bytes 是否与扩展名匹配。
    返回 (合法, 错误码)。
    """
    ext = _get_extension(filename)
    expected_magic = MAGIC_SIGNATURES.get(ext)
    if expected_magic is None:
        return False, "FILE_UNSUPPORTED_TYPE"

    try:
        actual_magic = _read_magic(file_path, len(expected_magic))
    except OSError:
        return False, "FILE_UNSUPPORTED_TYPE"

    if not actual_magic.startswith(expected_magic):
        return False, "FILE_UNSUPPORTED_TYPE"
    return True, ""


def validate_size(file_path: str, max_mb: int = DEFAULT_MAX_UPLOAD_MB) -> tuple[bool, str, int]:
    """
    校验文件大小。
    返回 (合法, 错误码, 字节数)。
    """
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return False, "FILE_UNSUPPORTED_TYPE", 0

    max_bytes = max_mb * 1024 * 1024
    if size > max_bytes:
        return False, "FILE_TOO_LARGE", size
    if size == 0:
        return False, "FILE_UNSUPPORTED_TYPE", 0
    return True, "", size


def compute_sha256(file_path: str) -> str:
    """计算文件 SHA-256 哈希"""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


def sanitize_filename(name: str) -> str:
    """清理文件名，移除路径分隔符和危险字符"""
    basename = Path(name).name
    # 仅保留安全字符
    safe = "".join(c for c in basename if c.isalnum() or c in "._- ()（）")
    return safe.strip() or "untitled"


# ---- 主入口 ----

def validate_upload(
    file_path: str,
    filename: str,
    max_mb: int = DEFAULT_MAX_UPLOAD_MB,
) -> ValidationResult:
    """
    完整的上传文件校验管线。
    依次执行：扩展名 → MIME → 大小 → SHA-256。
    返回 ValidationResult，调用方根据 is_valid 决定是否入库。
    """
    sanitized = sanitize_filename(filename)

    # 1. 扩展名
    ok, err = validate_extension(filename)
    if not ok:
        return ValidationResult(
            is_valid=False,
            filename=sanitized,
            error_code=err,
            error_message=f"不支持的文件类型: {_get_extension(filename)}",
        )

    # 2. MIME / magic bytes
    ok, err = validate_mime(file_path, filename)
    if not ok:
        return ValidationResult(
            is_valid=False,
            filename=sanitized,
            error_code=err,
            error_message="文件签名与实际类型不匹配",
        )

    # 3. 大小
    ok, err, size = validate_size(file_path, max_mb)
    if not ok:
        return ValidationResult(
            is_valid=False,
            filename=sanitized,
            size_bytes=size,
            error_code=err,
            error_message=f"文件大小异常: {size} bytes",
        )

    # 4. SHA-256
    sha = compute_sha256(file_path)

    return ValidationResult(
        is_valid=True,
        filename=sanitized,
        mime=ALLOWED_EXTENSIONS[_get_extension(filename)],
        sha256=sha,
        size_bytes=size,
    )
