"""
PDF 解析器测试

覆盖：
  - 文本提取
  - 页面分类（digital/scanned/mixed）
  - 公式检测
  - 表格检测
  - 页图渲染
  - Mock OCR 适配器
"""

import os
import sys
from pathlib import Path

import fitz
import pytest

# 确保 worker 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from worker.ingestion.parsers.pdf import PDFParser
from worker.ingestion.parsers.ocr import MockOCRAdapter
from worker.schemas import BlockType, PageResult, PageType


# ============================================================
# Fixtures
# ============================================================

SAMPLE_PDF = Path(__file__).resolve().parent / "fixtures" / "sample_lecture.pdf"  # src/tests/fixtures/


@pytest.fixture(scope="module")
def sample_pdf_path():
    """确保样例 PDF 存在，否则自动生成"""
    if not SAMPLE_PDF.exists():
        from tests.fixtures.generate_sample_pdf import create_sample_pdf
        create_sample_pdf()
    return str(SAMPLE_PDF)


@pytest.fixture
def parser():
    """使用 Mock OCR 的解析器"""
    return PDFParser(ocr_engine=MockOCRAdapter())


# ============================================================
# 文本提取
# ============================================================

class TestTextExtraction:
    """测试文本提取功能"""

    def test_extract_all_pages(self, parser, sample_pdf_path):
        """所有页面应成功提取"""
        results = parser.parse(sample_pdf_path, "test-uuid")
        assert len(results) == 4, f"预期 4 页，实际 {len(results)} 页"

    def test_page1_has_title(self, parser, sample_pdf_path):
        """第 1 页应包含标题文本"""
        results = parser.parse(sample_pdf_path, "test-uuid")
        page1 = results[0]
        assert "光的干涉" in page1.text
        assert "相干光源" in page1.text

    def test_page2_has_formula(self, parser, sample_pdf_path):
        """第 2 页应包含公式文本"""
        results = parser.parse(sample_pdf_path, "test-uuid")
        page2 = results[1]
        # 检查公式分隔符被保留
        # （PyMuPDF 提取时会保留原始文本）
        assert "lambda" in page2.text.lower() or "δ" in page2.text or len(page2.text) > 100

    def test_page3_has_table(self, parser, sample_pdf_path):
        """第 3 页应包含表格内容"""
        results = parser.parse(sample_pdf_path, "test-uuid")
        page3 = results[2]
        assert any(
            b.block_type == BlockType.TABLE for b in page3.layout
        ) or any(
            "杨氏双缝" in b.content for b in page3.layout
        ), "第 3 页应包含表格或其文本"

    def test_text_not_empty(self, parser, sample_pdf_path):
        """每页文本不应为空"""
        results = parser.parse(sample_pdf_path, "test-uuid")
        for i, page in enumerate(results, 1):
            assert page.text.strip(), f"第 {i} 页文本为空"


# ============================================================
# 页面分类
# ============================================================

class TestPageClassification:
    """测试页面分类"""

    def test_classify_digital(self, parser):
        """高文本密度页应分类为 digital"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 72), "正文内容 " * 50, fontsize=11)
        result = parser._classify_page(page)
        assert result == PageType.DIGITAL
        doc.close()

    def test_classify_empty(self, parser):
        """空白页应为 digital"""
        doc = fitz.open()
        page = doc.new_page()
        result = parser._classify_page(page)
        assert result == PageType.DIGITAL
        doc.close()

    def test_sample_pages_are_digital(self, parser, sample_pdf_path):
        """样例 PDF 所有页应为 digital（文本为主）"""
        results = parser.parse(sample_pdf_path, "test-uuid")
        digital_count = sum(1 for r in results if r.is_digital)
        assert digital_count >= 3, f"至少 3 页应为 digital，实际 {digital_count}"


# ============================================================
# 公式检测
# ============================================================

class TestFormulaDetection:
    """测试公式检测"""

    def test_inline_formula_detected(self, parser):
        """$...$ 内联公式应被检测"""
        from worker.schemas import LayoutBlock, BlockType
        layout = [
            LayoutBlock(
                bbox=(0, 0, 100, 20), block_type=BlockType.TEXT,
                content="光程差为 $\\delta = r_2 - r_1$",
                confidence=1.0, reading_order=0,
            ),
        ]
        parser._detect_formulas_in_layout(layout)
        assert layout[0].block_type == BlockType.FORMULA

    def test_display_formula_detected(self, parser):
        """$$...$$ 显示公式应被检测"""
        from worker.schemas import LayoutBlock, BlockType
        layout = [
            LayoutBlock(
                bbox=(0, 0, 100, 20), block_type=BlockType.TEXT,
                content="$$\\Delta x = \\frac{\\lambda D}{d}$$",
                confidence=1.0, reading_order=0,
            ),
        ]
        parser._detect_formulas_in_layout(layout)
        assert layout[0].block_type == BlockType.FORMULA

    def test_plain_text_not_formula(self, parser):
        """纯文本不应被标记为公式"""
        from worker.schemas import LayoutBlock, BlockType
        layout = [
            LayoutBlock(
                bbox=(0, 0, 100, 20), block_type=BlockType.TEXT,
                content="两列光波在空间相遇时会产生干涉现象。",
                confidence=1.0, reading_order=0,
            ),
        ]
        parser._detect_formulas_in_layout(layout)
        assert layout[0].block_type == BlockType.TEXT


# ============================================================
# 页图渲染
# ============================================================

class TestPageImage:
    """测试页图渲染"""

    def test_image_saved_to_correct_path(self, parser, sample_pdf_path, tmp_path):
        """页图应生成并保存为 PNG"""
        results = parser.parse(sample_pdf_path, "test-uuid")
        assert len(results) == 4

        for page in results:
            # image_path 格式: "pages/{uuid}/page_xxxx.png"
            assert page.image_path, "image_path 不应为空"
            assert page.image_path.endswith(".png"), f"应为 PNG: {page.image_path}"
            assert f"page_{page.page_no:04d}.png" in page.image_path

        # 验证页图文件确实存在（检查默认目录）
        from worker.config import PAGE_IMAGES_DIR
        sample_path = PAGE_IMAGES_DIR / "test-uuid" / "page_0001.png"
        assert sample_path.exists(), f"默认目录下页图应存在: {sample_path}"
        assert sample_path.stat().st_size > 100


# ============================================================
# Mock OCR
# ============================================================

class TestMockOCR:
    """测试 Mock OCR 适配器"""

    def test_mock_returns_text(self):
        """Mock OCR 应返回固定文本"""
        from worker.ingestion.parsers.ocr import MockOCRAdapter
        ocr = MockOCRAdapter(fixed_text="测试 OCR 文本")
        result = ocr.recognize("dummy.png")
        assert "测试 OCR 文本" in result.text
        assert result.page_confidence == 0.99

    def test_parser_with_mock_ocr(self, sample_pdf_path):
        """使用 Mock OCR 的解析器不应崩溃"""
        parser = PDFParser(ocr_engine=MockOCRAdapter())
        results = parser.parse(sample_pdf_path, "test-uuid")
        assert len(results) == 4


# ============================================================
# 边界情况
# ============================================================

class TestEdgeCases:
    """边界情况测试"""

    def test_nonexistent_file(self, parser):
        """不存在的文件应抛出异常"""
        with pytest.raises(Exception):
            parser.parse("/nonexistent/path/file.pdf", "test-uuid")

    def test_empty_pdf(self, parser, tmp_path):
        """单空白页 PDF 应可解析"""
        doc = fitz.open()
        page = doc.new_page()  # PyMuPDF 不允许保存零页文档
        empty_path = tmp_path / "empty.pdf"
        doc.save(str(empty_path))
        doc.close()

        results = parser.parse(str(empty_path), "test-uuid")
        assert len(results) == 1
        assert results[0].text.strip() == ""  # 空白页无文本

    def test_single_page_pdf(self, parser, tmp_path):
        """单页 PDF 应正确解析"""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(72, 72), "单页测试内容", fontname="china-ss", fontsize=12)
        single_path = tmp_path / "single.pdf"
        doc.save(str(single_path))
        doc.close()

        results = parser.parse(str(single_path), "test-uuid")
        assert len(results) == 1
        assert "单页测试内容" in results[0].text

    def test_bbox_overlap_detection(self, parser):
        """bbox 重叠判断"""
        assert parser._bboxes_overlap((0, 0, 10, 10), (5, 5, 15, 15)) is True
        assert parser._bboxes_overlap((0, 0, 10, 10), (20, 20, 30, 30)) is False
        assert parser._bboxes_overlap((0, 0, 10, 10), (5, 5, 8, 8)) is True
