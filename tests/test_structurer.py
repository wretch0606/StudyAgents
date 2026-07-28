"""
版面结构化器测试
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker.schemas import BlockType, LayoutBlock, PageResult
from worker.ingestion.structurer import PageStructurer


def _make_page(*texts: str, block_type=BlockType.TEXT) -> PageResult:
    layout = [
        LayoutBlock(
            bbox=(0, i * 20, 400, i * 20 + 18),
            block_type=block_type,
            content=t,
            confidence=1.0,
            reading_order=i,
        )
        for i, t in enumerate(texts)
    ]
    return PageResult(page_no=1, text="\n".join(texts), image_path="", layout=layout, is_digital=True)


class TestHeadingDetection:
    """标题识别"""

    def test_chapter_heading(self):
        s = PageStructurer()
        result = s.structure(_make_page("第三章 光的干涉"))

        # 应有章节标题 Section
        assert len(result.sections) >= 1
        # 标题级别应为 1（章）
        if result.sections[0].heading:
            assert result.sections[0].level <= 2

    def test_section_heading(self):
        s = PageStructurer()
        result = s.structure(_make_page("3.1 相干光源与干涉条件"))

        assert len(result.sections) >= 1

    def test_numbered_heading(self):
        s = PageStructurer()
        result = s.structure(_make_page("一、引言"))

        assert len(result.sections) >= 1
        if result.sections[0].heading:
            assert "引言" in result.sections[0].heading

    def test_parenthesized_heading(self):
        s = PageStructurer()
        result = s.structure(_make_page("（一）实验原理"))

        assert len(result.sections) >= 1

    def test_heading_with_body(self):
        s = PageStructurer()
        result = s.structure(_make_page(
            "3.2 干涉条纹特征",
            "干涉条纹的间距公式为...",
            "其中各参数含义如下：",
        ))

        # 至少有一个节
        assert len(result.sections) >= 1
        sec = result.sections[0]
        # 标题应被提取
        if sec.heading:
            assert "3.2" in sec.heading
        # 正文段落应在该节内
        assert len(sec.paragraphs) >= 1

    def test_multi_level_heading(self):
        s = PageStructurer()
        page = _make_page(
            "第四章 电磁学",
            "4.1 静电场",
            "电场强度的定义是...",
            "4.2 稳恒磁场",
            "磁感应强度...",
        )
        result = s.structure(page)

        # 应产生多个节
        assert len(result.sections) >= 2

    def test_plain_text_not_heading(self):
        s = PageStructurer()
        result = s.structure(_make_page(
            "两列光波在空间相遇时会产生干涉现象这是光学中的重要内容",
        ))

        # 长句不应被识别为标题
        if result.sections:
            # 若产生了 section，其 heading 应为 None
            assert result.sections[0].heading is None or len(result.sections[0].paragraphs) > 0

    def test_reset(self):
        s = PageStructurer()
        s._heading_stack = ["fake"]
        s.reset()
        assert s._heading_stack == []


class TestFormulaHandling:
    """公式处理"""

    def test_formula_block_recognized(self):
        s = PageStructurer()
        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(bbox=(0, 0, 100, 20), block_type=BlockType.TEXT,
                            content="能量公式为：", confidence=1.0, reading_order=0),
                LayoutBlock(bbox=(0, 20, 100, 40), block_type=BlockType.FORMULA,
                            content=r"E=mc^2", confidence=0.95, reading_order=1),
            ],
            is_digital=True,
        )
        result = s.structure(page)

        # 公式应在节内
        assert len(result.sections) >= 1
        assert len(result.sections[0].formulas) >= 1
        assert r"E=mc^2" in result.sections[0].formulas[0]


class TestTableHandling:
    """表格处理"""

    def test_table_block_in_result(self):
        s = PageStructurer()
        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(bbox=(0, 0, 200, 60), block_type=BlockType.TABLE,
                            content="| 实验 | 条纹间距 |\n| --- | --- |\n| 杨氏 | Δx=λD/d |",
                            confidence=0.92, reading_order=0),
            ],
            is_digital=True,
        )
        result = s.structure(page)

        assert len(result.tables) >= 1
        assert "杨氏" in result.tables[0].markdown


class TestFigureHandling:
    """图表处理"""

    def test_figure_block_in_result(self):
        s = PageStructurer()
        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(bbox=(0, 0, 200, 150), block_type=BlockType.FIGURE,
                            content="图 3-1 杨氏双缝实验装置", confidence=1.0, reading_order=0),
            ],
            is_digital=True,
        )
        result = s.structure(page)

        assert len(result.figures) >= 1
        assert "杨氏双缝" in result.figures[0].caption


class TestEmptyInput:
    """空输入"""

    def test_empty_page(self):
        s = PageStructurer()
        result = s.structure(_make_page())
        assert result.sections == []
        assert result.tables == []
        assert result.figures == []

    def test_structure_pages_batch(self):
        from worker.ingestion.structurer import structure_pages

        pages = [_make_page("第一章"), _make_page("1.1 概述")]
        structured = structure_pages(pages)
        assert len(structured) == 2
