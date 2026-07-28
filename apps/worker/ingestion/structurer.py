"""
版面结构化器

将 LayoutBlock 列表转为层级结构：
  - 标题层级识别 (H1-H4)
  - 段落与章节归属
  - 公式与上下文绑定
  - 表格行列标注
  - 图表区域提取
"""

import logging
import re
from typing import Optional

from apps.worker.schemas import (
    BlockType,
    FigureBlock,
    LayoutBlock,
    PageResult,
    Section,
    StructuredPage,
    TableBlock,
)

logger = logging.getLogger(__name__)

# 章节标题模式
_CHAPTER_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十\d]+章\s*.+"),    # 第X章 xxx
    re.compile(r"^第[一二三四五六七八九十\d]+节\s*.+"),    # 第X节 xxx
    re.compile(r"^\d+(\.\d+){0,2}\s+\S"),                # 1.1 xxx
    re.compile(r"^[一二三四五六七八九十]、\s*\S"),         # 一、xxx
    re.compile(r"^[（(][一二三四五六七八九十\d]+[)）]\s*\S"), # (一) xxx
    re.compile(r"^[A-D][.、]\s*\S"),                     # A. xxx (附录)
]

# 小节标题模式（字面关键词）
_SUB_PATTERNS = [
    re.compile(r"^[（(]\d+[)）]"),                        # (1)
    re.compile(r"^\d+[.、\)]\s*\S"),                     # 1. xxx
    re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]"),                    # ①②
]


class PageStructurer:
    """页面版面结构化器"""

    def __init__(self):
        self._heading_stack: list[Section] = []  # 跨页标题栈
        self._level_base_size: Optional[float] = None  # 基准字号

    def structure(self, page: PageResult) -> StructuredPage:
        """
        将 PageResult.layout 转为 StructuredPage。

        跨页标题通过 self._heading_stack 延续。
        """
        sections: list[Section] = []
        tables: list[TableBlock] = []
        figures: list[FigureBlock] = []

        current_section: Optional[Section] = None

        for block in page.layout:
            bt = block.block_type

            if bt == BlockType.TABLE:
                tables.append(TableBlock(
                    markdown=block.content,
                    page_no=page.page_no,
                    bbox=block.bbox,
                ))
                continue

            if bt == BlockType.FIGURE:
                figures.append(FigureBlock(
                    image_path="",
                    caption=block.content,
                    page_no=page.page_no,
                    bbox=block.bbox,
                ))
                continue

            # 文本/公式块（公式不参与标题检测）
            is_heading, level = (False, 0) if bt == BlockType.FORMULA else self._is_heading(block)

            if is_heading and level <= 2:
                # 大标题 → 新章节
                if current_section and current_section.paragraphs:
                    sections.append(current_section)
                current_section = Section(
                    heading=block.content.replace("[HEADING] ", ""),
                    level=level,
                )
                # 更新栈
                self._heading_stack = [s for s in self._heading_stack if s.level < level]
                self._heading_stack.append(current_section)

            elif is_heading and level >= 3:
                # 小标题 → 当前节内新段落
                if current_section is None:
                    current_section = Section(heading=None, level=1)
                current_section.paragraphs.append(block.content)

            elif bt == BlockType.FORMULA:
                if current_section is None:
                    current_section = Section(heading=None, level=1)
                current_section.formulas.append(block.content)
                # 公式同时也作为段落（便于检索）
                current_section.paragraphs.append(f"[公式] {block.content}")

            else:
                # 普通文本
                if current_section is None:
                    current_section = Section(heading=None, level=1)
                current_section.paragraphs.append(block.content)

        # 最后一节（有标题或有内容才保留）
        if current_section and (
            current_section.heading
            or current_section.paragraphs
            or current_section.formulas
        ):
            sections.append(current_section)

        return StructuredPage(
            page_no=page.page_no,
            sections=sections,
            tables=tables,
            figures=figures,
        )

    def _is_heading(self, block: LayoutBlock) -> tuple[bool, int]:
        """
        判断是否为标题，返回 (is_heading, level)。

        level: 1=章, 2=节, 3=小节, 4=子小节
        """
        text = block.content.strip()

        # HEADING 标记（由 PDF 解析器标记）
        if text.startswith("[HEADING]"):
            text = text.replace("[HEADING] ", "")

            # 判断层级
            for i, pat in enumerate(_CHAPTER_PATTERNS):
                if pat.match(text):
                    return True, min(i // 2 + 1, 2)  # 0-1→1, 2-3→2

            for pat in _SUB_PATTERNS:
                if pat.match(text):
                    return True, 3

            # 纯短文本（可能是标题）
            if len(text) <= 30:
                return True, 2

            return True, 1

        # 自动检测模式
        for i, pat in enumerate(_CHAPTER_PATTERNS):
            if pat.match(text) and len(text) <= 60:
                return True, min(i // 2 + 1, 2)

        for pat in _SUB_PATTERNS:
            if pat.match(text) and len(text) <= 40:
                return True, 3

        # 短文本 + 无标点结尾 → 可能是标题
        if len(text) <= 25 and not re.search(r"[。！？；，、]$", text):
            return True, 3

        return False, 0

    def reset(self):
        """重置跨页状态（开始新文档时调用）"""
        self._heading_stack = []
        self._level_base_size = None


# ================================================================
# 便捷函数
# ================================================================

def structure_pages(pages: list[PageResult]) -> list[StructuredPage]:
    """批量结构化页面"""
    structurer = PageStructurer()
    return [structurer.structure(p) for p in pages]
