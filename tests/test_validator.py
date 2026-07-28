"""
文件校验器测试

覆盖：扩展名 / MIME / 大小 / SHA-256 / 文件名清理 / 去重 / 边界
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.ingestion.validator import (
    compute_sha256,
    sanitize_filename,
    validate_extension,
    validate_mime,
    validate_size,
    validate_upload,
)


class TestExtensionValidation:
    """扩展名校验"""

    def test_allowed_pdf(self):
        ok, _ = validate_extension("讲义.pdf")
        assert ok

    def test_allowed_docx(self):
        ok, _ = validate_extension("复习资料.docx")
        assert ok

    def test_allowed_pptx(self):
        ok, _ = validate_extension("课件.pptx")
        assert ok

    def test_allowed_jpg(self):
        ok, _ = validate_extension("photo.jpg")
        assert ok

    def test_allowed_png(self):
        ok, _ = validate_extension("screenshot.png")
        assert ok

    def test_rejected_exe(self):
        ok, err = validate_extension("virus.exe")
        assert not ok
        assert err == "FILE_UNSUPPORTED_TYPE"

    def test_rejected_txt(self):
        ok, _ = validate_extension("notes.txt")
        assert not ok

    def test_rejected_no_extension(self):
        ok, _ = validate_extension("unknown_file")
        assert not ok

    def test_case_insensitive(self):
        ok, _ = validate_extension("FILE.PDF")
        assert ok


class TestMIMEValidation:
    """MIME / Magic Bytes 校验"""

    def test_valid_pdf(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4\n%some content")
        ok, _ = validate_mime(str(f), "test.pdf")
        assert ok

    def test_valid_png(self, tmp_path):
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        ok, _ = validate_mime(str(f), "test.png")
        assert ok

    def test_mismatched_magic(self, tmp_path):
        f = tmp_path / "fake.pdf"
        f.write_bytes(b"Hello World!")
        ok, err = validate_mime(str(f), "fake.pdf")
        assert not ok
        assert err == "FILE_UNSUPPORTED_TYPE"

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        ok, _ = validate_mime(str(f), "empty.pdf")
        assert not ok


class TestSizeValidation:
    """文件大小校验"""

    def test_normal_size(self, tmp_path):
        f = tmp_path / "normal.pdf"
        f.write_bytes(b"x" * 1024)
        ok, _, size = validate_size(str(f), max_mb=10)
        assert ok
        assert size == 1024

    def test_exceeds_limit(self, tmp_path):
        f = tmp_path / "huge.pdf"
        f.write_bytes(b"x" * (2 * 1024 * 1024))
        ok, err, _ = validate_size(str(f), max_mb=1)
        assert not ok
        assert err == "FILE_TOO_LARGE"

    def test_zero_byte_file(self, tmp_path):
        f = tmp_path / "zero.pdf"
        f.write_bytes(b"")
        ok, _, _ = validate_size(str(f))
        assert not ok


class TestSHA256:
    """哈希计算"""

    def test_known_hash(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello world")
        h = compute_sha256(str(f))
        assert len(h) == 64
        # SHA-256 of "hello world" is deterministic
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_different_files_different_hash(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"aaa")
        f2.write_bytes(b"bbb")
        assert compute_sha256(str(f1)) != compute_sha256(str(f2))

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "x.bin"
        f2 = tmp_path / "y.bin"
        f1.write_bytes(b"identical")
        f2.write_bytes(b"identical")
        assert compute_sha256(str(f1)) == compute_sha256(str(f2))


class TestSanitizeFilename:
    """文件名清理"""

    def test_normal_name(self):
        assert sanitize_filename("讲义.pdf") == "讲义.pdf"

    def test_path_traversal(self):
        result = sanitize_filename("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result

    def test_special_chars(self):
        result = sanitize_filename("a<b>c:d*e?f\"g|h")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_chinese_name(self):
        result = sanitize_filename("光学讲义（第三章）.pdf")
        assert "光学讲义" in result

    def test_very_long_name(self):
        long_name = "a" * 500 + ".pdf"
        result = sanitize_filename(long_name)
        assert len(result) == 504  # 500 个 'a' + '.pdf'


class TestFullValidation:
    """完整校验管线"""

    def test_valid_pdf_passes(self, tmp_path):
        f = tmp_path / "valid.pdf"
        f.write_bytes(b"%PDF-1.4\n" + b"x" * 2048)

        result = validate_upload(str(f), "valid.pdf", max_mb=10)
        assert result.is_valid
        assert result.mime == "application/pdf"
        assert len(result.sha256) == 64
        assert result.size_bytes > 100
        assert result.error_code is None

    def test_invalid_file_fails(self, tmp_path):
        f = tmp_path / "bad.txt"
        f.write_bytes(b"hello")

        result = validate_upload(str(f), "bad.txt")
        assert not result.is_valid
        assert result.error_code is not None
        assert result.error_message is not None
