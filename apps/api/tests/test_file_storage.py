"""文件校验与存储测试 — 不访问真实大文件。"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---- 辅助函数 ----

def _stream(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


# ============================================================
# 扩展名校验
# ============================================================

def test_validate_extension_allows_pdf() -> None:
    from apps.api.services.file_storage import validate_extension
    assert validate_extension("doc.pdf") == ".pdf"
    assert validate_extension("Doc.PDF") == ".pdf"


def test_validate_extension_allows_docx() -> None:
    from apps.api.services.file_storage import validate_extension
    assert validate_extension("notes.docx") == ".docx"


def test_validate_extension_allows_jpg_png() -> None:
    from apps.api.services.file_storage import validate_extension
    assert validate_extension("img.jpg") == ".jpg"
    assert validate_extension("img.jpeg") == ".jpeg"
    assert validate_extension("img.png") == ".png"


def test_validate_extension_rejects_unknown() -> None:
    from apps.api.services.file_storage import FileValidationError, validate_extension
    with pytest.raises(FileValidationError):
        validate_extension("virus.exe")
    with pytest.raises(FileValidationError):
        validate_extension("data.txt")
    with pytest.raises(FileValidationError):
        validate_extension("noext")


# ============================================================
# MIME 校验
# ============================================================

def test_validate_mime_ok() -> None:
    from apps.api.services.file_storage import validate_mime
    validate_mime("application/pdf", ".pdf")  # 不抛异常


def test_validate_mime_mismatch() -> None:
    from apps.api.services.file_storage import FileValidationError, validate_mime
    with pytest.raises(FileValidationError, match="MIME"):
        validate_mime("text/html", ".pdf")


# ============================================================
# 魔数签名校验
# ============================================================

def test_validate_magic_pdf() -> None:
    from apps.api.services.file_storage import validate_magic
    validate_magic(b"%PDF-1.4\n%...", ".pdf")  # 不抛异常


def test_validate_magic_wrong() -> None:
    from apps.api.services.file_storage import FileValidationError, validate_magic
    with pytest.raises(FileValidationError, match="不匹配"):
        validate_magic(b"GIF89a...", ".pdf")


def test_validate_magic_png() -> None:
    from apps.api.services.file_storage import validate_magic
    validate_magic(b"\x89PNG\r\n\x1a\n\x00\x00", ".png")


def test_validate_magic_jpg() -> None:
    from apps.api.services.file_storage import validate_magic
    validate_magic(b"\xff\xd8\xff\xe0\x00\x10JFIF", ".jpg")


# ============================================================
# 文件名清洗
# ============================================================

def test_sanitize_filename_path_traversal() -> None:
    from apps.api.services.file_storage import sanitize_filename
    assert ".." not in sanitize_filename("../../../etc/passwd.pdf")
    assert ".." not in sanitize_filename("..%2e%2e\\etc.pdf")


def test_sanitize_filename_dangerous_chars() -> None:
    from apps.api.services.file_storage import sanitize_filename
    name = sanitize_filename('test<>:"/\\|?*.pdf')
    assert name == "test_________.pdf"


def test_sanitize_filename_blank() -> None:
    from apps.api.services.file_storage import sanitize_filename
    assert sanitize_filename("...") == "unnamed"


# ============================================================
# 大小限制
# ============================================================

def test_file_too_large() -> None:
    from apps.api.services.file_storage import FileValidationError, _stream_and_hash
    big = io.BytesIO(b"x" * (101 * 1024 * 1024))
    with pytest.raises(FileValidationError):
        _stream_and_hash(big)

    # 刚好 1MB 应通过
    small = io.BytesIO(b"y" * (1024 * 1024))
    _, sha, size = _stream_and_hash(small)
    assert len(sha) == 64
    assert size == 1024 * 1024


def test_empty_file_valid() -> None:
    from apps.api.services.file_storage import _stream_and_hash
    empty = io.BytesIO(b"")
    _, sha, size = _stream_and_hash(empty)
    assert sha == hashlib.sha256(b"").hexdigest()
    assert size == 0


# ============================================================
# 原子保存
# ============================================================

def test_save_file_atomic(tmp_path, monkeypatch) -> None:
    """文件成功保存到目标路径。"""
    import hashlib

    from apps.api.services.file_storage import save_file

    # 使用临时目录模拟 files_root
    monkeypatch.setattr("apps.api.services.file_storage.settings.files_root", str(tmp_path))

    data = b"%PDF-1.4 fake pdf content"
    source = io.BytesIO(data)
    path, sha, size = save_file(source, filename="test.pdf")

    assert Path(path).exists()
    assert Path(path).parent == tmp_path
    assert sha == hashlib.sha256(data).hexdigest()
    assert size == len(data)


def test_save_file_cleans_filename(tmp_path, monkeypatch) -> None:
    """文件名被清洗，路径不含危险字符。"""
    from apps.api.services.file_storage import save_file

    monkeypatch.setattr("apps.api.services.file_storage.settings.files_root", str(tmp_path))

    source = io.BytesIO(b"\x89PNG\r\n\x1a\nfake png")
    path, _, _ = save_file(source, filename="../../../evil<>.png")

    assert ".." not in path
    assert "<" not in path
    assert Path(path).exists()


# ============================================================
# SHA-256 去重
# ============================================================

@pytest.mark.asyncio
async def test_check_duplicate_found() -> None:
    """已有相同 SHA-256 文档时返回文档信息。"""
    import uuid

    from apps.api.services.file_storage import check_duplicate

    doc_id = str(uuid.uuid4())
    test_sha = "a" * 64

    # 模拟 DB session
    class FakeSession:
        async def execute(self, stmt):
            return _FakeResult([
                type("Doc", (), {
                    "id": doc_id, "name": "existing.pdf",
                    "sha256": test_sha, "status": "active",
                })
            ])

        async def commit(self): pass
        async def rollback(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    result = await check_duplicate(test_sha, db_session=FakeSession())
    assert result is not None
    assert result["document_id"] == doc_id
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_check_duplicate_not_found() -> None:
    """无重复时返回 None。"""
    from apps.api.services.file_storage import check_duplicate

    class FakeSession:
        async def execute(self, stmt):
            return _FakeResult(None)

    result = await check_duplicate("nonexistent", db_session=FakeSession())
    assert result is None


class _FakeResult:
    def __init__(self, val):
        self._val = val

    def scalar_one_or_none(self):
        rows = self._val if isinstance(self._val, list) else [self._val]
        return rows[0] if rows and rows[0] is not None else None


# ============================================================
# 双重扩展名
# ============================================================

def test_double_extension_normalized() -> None:
    from apps.api.services.file_storage import FileValidationError, validate_extension
    # test.pdf.exe → 后缀 .exe 不在白名单 → 应拒绝
    with pytest.raises(FileValidationError):
        validate_extension("test.pdf.exe")


def test_double_extension_valid() -> None:
    from apps.api.services.file_storage import validate_extension
    # .tar.gz.pdf → .pdf 在白名单中 OK
    assert validate_extension("backup.tar.gz.pdf") == ".pdf"


# ============================================================
# 完整校验流程
# ============================================================

def test_full_validation_flow_pdf() -> None:
    """完整流程：扩展名+MIME+魔数 三步校验通过。"""
    from apps.api.services.file_storage import (
        validate_extension,
        validate_magic,
        validate_mime,
    )

    ext = validate_extension("lecture.pdf")
    assert ext == ".pdf"
    validate_mime("application/pdf", ext)
    validate_magic(b"%PDF-1.7\n", ext)


def test_validate_mime_empty_allowed() -> None:
    """MIME 为空时不报错（浏览器可能不传）。"""
    from apps.api.services.file_storage import validate_mime
    validate_mime("", ".pdf")  # 不抛异常
    validate_mime(None, ".pdf")  # 不抛异常
