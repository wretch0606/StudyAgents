"""
PDF 解析器（增强版）

基于 PyMuPDF (fitz)，支持：
  - 数字文本页：文本提取 + 字体分析 + 标题识别 + 公式检测 + 表格检测
  - 扫描件：委托 PaddleOCR 全管线
  - 混合页：文本区直接提取 + 图片区 OCR
  - 页图渲染：150 DPI PNG，按 doc_uuid 组织存储
  - 图片提取：提取 PDF 内嵌图片
  - 目录提取：自动构建 section_path
"""

import logging
import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from apps.worker.config import DIGITAL_TEXT_MIN_CHARS, OCR_REVIEW_THRESHOLD, PAGE_IMAGES_DIR
from apps.worker.ingestion.parsers.ocr import OCRInterface, OCRResult, create_ocr_engine
from apps.worker.schemas import BlockType, LayoutBlock, PageResult, PageType

logger = logging.getLogger(__name__)


class PDFParser:
    """
    PDF 文档解析器（增强版）。

    使用示例：
        parser = PDFParser(ocr_engine=create_ocr_engine("paddle"))
        results = parser.parse("lecture.pdf", doc_uuid="abc123")
    """

    def __init__(
        self,
        ocr_engine: Optional[OCRInterface] = None,
        min_text_chars: int = DIGITAL_TEXT_MIN_CHARS,
        ocr_review_threshold: float = OCR_REVIEW_THRESHOLD,
        render_dpi: int = 150,
    ):
        self.ocr = ocr_engine or create_ocr_engine("none")
        self.min_text_chars = min_text_chars
        self.ocr_review_threshold = ocr_review_threshold
        self.render_dpi = render_dpi

        # 公式检测正则
        self._formula_pattern = re.compile(
            r"(?:\$\$[\s\S]*?\$\$)|(?:\$[^$]*?\$)|(?:\\(?:begin|end)\{[a-z*]+\})"
        )

    # ================================================================
    # 主入口
    # ================================================================

    def parse(self, file_path: str, doc_uuid: str) -> list[PageResult]:
        """
        解析 PDF，返回每页 PageResult。

        Args:
            file_path: PDF 文件绝对路径
            doc_uuid:  文档 UUID，用于页图路径隔离

        Returns:
            按页码排序的 PageResult 列表
        """
        doc = fitz.open(file_path)
        total_pages = doc.page_count
        logger.info(f"开始解析 PDF: {total_pages} 页, doc={doc_uuid}")

        results: list[PageResult] = []

        # 确保页图目录存在
        page_dir = PAGE_IMAGES_DIR / doc_uuid
        page_dir.mkdir(parents=True, exist_ok=True)

        # 提取目录（用于后续 section_path 填充）
        toc = self._extract_toc(doc)

        for page_no, page in enumerate(doc, start=1):
            logger.debug(f"  处理第 {page_no}/{total_pages} 页")

            # 1. 页面分类
            page_type = self._classify_page(page)

            # 2. 页图渲染（所有页面都需要）
            image_path = self._render_page_image(page, page_no, doc_uuid)

            # 3. 按类型处理
            if page_type == PageType.DIGITAL:
                result = self._extract_digital(page, page_no, doc_uuid, image_path)
            elif page_type == PageType.SCANNED:
                result = self._extract_scanned(page, page_no, doc_uuid, image_path)
            else:
                result = self._extract_mixed(page, page_no, doc_uuid, image_path)

            results.append(result)

        doc.close()
        logger.info(
            f"解析完成: digital={sum(1 for r in results if r.is_digital)}, "
            f"scanned={sum(1 for r in results if not r.is_digital)}, "
            f"avg_confidence={sum(r.confidence for r in results) / len(results):.3f}"
        )
        return results

    # ================================================================
    # 页面分类
    # ================================================================

    def _classify_page(self, page: fitz.Page) -> PageType:
        """
        分类页面类型。

        启发式规则：
          1. 提取字符数 ≥ min_text_chars  → DIGITAL
          2. 有图片但字符数不足           → SCANNED
          3. 字符数在阈值边缘且有图片      → MIXED

        后续可根据 text_coverage_ratio 进一步细化。
        """
        text = page.get_text()
        char_count = len(text.strip())

        # 获取页面图片数量
        page_dict = page.get_text("dict")
        image_blocks = sum(1 for b in page_dict.get("blocks", []) if b.get("type", -1) == 1)

        if char_count >= self.min_text_chars:
            # 文本足够 → 检查是否有值得 OCR 的图片区
            if image_blocks >= 3 and char_count < self.min_text_chars * 3:
                return PageType.DIGITAL  # 有图但文本为主，仍算数字页
            return PageType.DIGITAL

        if image_blocks > 0:
            # 文本很少但有图 → 混合页
            if char_count >= 20:
                return PageType.DIGITAL  # 图片标注，仍可提取文本
            return PageType.SCANNED

        # 无文本无图片 → 空白页，按数字处理
        return PageType.DIGITAL

    # ================================================================
    # 数字文本页处理
    # ================================================================

    def _extract_digital(
        self, page: fitz.Page, page_no: int, doc_uuid: str, image_path: str
    ) -> PageResult:
        """
        处理数字文本页。

        顺序：文本提取 → 版面分析 → 公式检测 → 表格检测 → 标题识别
        """
        # 文本提取（带格式信息）
        page_dict = page.get_text("dict")
        text = page.get_text()

        # 版面结构
        layout = self._parse_layout(page_dict)

        # 公式检测（在文本块中标注 LaTeX）
        self._detect_formulas_in_layout(layout)

        # 表格检测（在文本块中标注 Markdown 表格）
        self._detect_tables_in_layout(page, layout)

        # 标题识别（基于字体大小和粗体）
        self._mark_headings_in_layout(layout)

        # 页面级置信度
        confidence = self._compute_layout_confidence(layout)

        return PageResult(
            page_no=page_no,
            text=text,
            image_path=image_path,
            layout=layout,
            confidence=confidence,
            is_digital=True,
        )

    # ================================================================
    # 扫描件处理
    # ================================================================

    def _extract_scanned(
        self, page: fitz.Page, page_no: int, doc_uuid: str, image_path: str
    ) -> PageResult:
        """
        处理扫描件：委托 OCR 引擎。
        """
        abs_path = PAGE_IMAGES_DIR / image_path

        ocr_result: OCRResult = self.ocr.recognize(str(abs_path), page_no)

        return PageResult(
            page_no=page_no,
            text=ocr_result.text,
            image_path=image_path,
            layout=ocr_result.blocks,
            confidence=ocr_result.page_confidence,
            is_digital=False,
        )

    # ================================================================
    # 混合页处理
    # ================================================================

    def _extract_mixed(
        self, page: fitz.Page, page_no: int, doc_uuid: str, image_path: str
    ) -> PageResult:
        """
        处理混合页：文本区直接提取 + 图片区 OCR。

        策略：
          1. 先用 PyMuPDF 提取所有文本块
          2. 识别图片区域
          3. 对图片区域单独裁剪 → OCR
          4. 合并结果，按阅读顺序排列
        """
        page_dict = page.get_text("dict")
        layout: list[LayoutBlock] = []
        full_text_parts: list[str] = []

        reading_order = 0
        text_confidences: list[float] = []

        for block in page_dict.get("blocks", []):
            if block.get("type", -1) == 0:
                # 文本块 → 直接提取
                for line in block.get("lines", []):
                    line_text = "".join(
                        span.get("text", "") for span in line.get("spans", [])
                    ).strip()
                    if line_text:
                        layout.append(LayoutBlock(
                            bbox=tuple(line["bbox"]),
                            block_type=BlockType.TEXT,
                            content=line_text,
                            confidence=0.95,
                            reading_order=reading_order,
                        ))
                        full_text_parts.append(line_text)
                        text_confidences.append(0.95)
                        reading_order += 1

            elif block.get("type", -1) == 1:
                # 图片块 → 裁剪并 OCR
                bbox = block["bbox"]
                cropped = self._crop_image_region(page, bbox, page_no, reading_order)
                if cropped:
                    ocr_result = self.ocr.recognize_bytes(cropped, page_no)
                    if ocr_result.text.strip():
                        layout.append(LayoutBlock(
                            bbox=tuple(bbox),
                            block_type=BlockType.FIGURE,
                            content=ocr_result.text,
                            confidence=ocr_result.page_confidence,
                            reading_order=reading_order,
                        ))
                        full_text_parts.append(ocr_result.text)
                        text_confidences.append(ocr_result.page_confidence)
                        reading_order += 1

        text = "\n".join(full_text_parts)
        confidence = sum(text_confidences) / len(text_confidences) if text_confidences else 0.5

        return PageResult(
            page_no=page_no,
            text=text,
            image_path=image_path,
            layout=layout,
            confidence=round(confidence, 4),
            is_digital=False,
        )

    # ================================================================
    # 页图渲染
    # ================================================================

    def _render_page_image(self, page: fitz.Page, page_no: int, doc_uuid: str) -> str:
        """
        渲染页图为 PNG，返回相对路径。
        """
        mat = fitz.Matrix(self.render_dpi / 72, self.render_dpi / 72)
        pix = page.get_pixmap(matrix=mat)

        # 如果图片过大（CMYK 等），转为 RGB
        if pix.n > 4:
            pix = fitz.Pixmap(fitz.csRGB, pix)

        filename = f"page_{page_no:04d}.png"
        rel_path = f"{doc_uuid}/{filename}"  # 相对于 PAGE_IMAGES_DIR
        abs_path = PAGE_IMAGES_DIR / doc_uuid / filename
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(abs_path))
        return rel_path

    # ================================================================
    # 版面解析
    # ================================================================

    def _parse_layout(self, page_dict: dict) -> list[LayoutBlock]:
        """
        从 PyMuPDF dict 提取版面块。

        改进：按 block → line 两级结构解析，保留字体信息。
        """
        blocks: list[LayoutBlock] = []
        order = 0

        for block in page_dict.get("blocks", []):
            block_type = block.get("type", -1)

            if block_type == 0:  # 文本块
                for line in block.get("lines", []):
                    text = "".join(
                        span.get("text", "") for span in line.get("spans", [])
                    ).strip()
                    if not text:
                        continue

                    # 提取字体信息（用于标题识别）
                    font_info = self._extract_font_info(line)

                    blocks.append(LayoutBlock(
                        bbox=tuple(line["bbox"]),
                        block_type=BlockType.TEXT,
                        content=text,
                        confidence=0.98,
                        reading_order=order,
                        # 附加信息通过 content 前缀传递（后续结构化阶段处理）
                    ))
                    order += 1

            elif block_type == 1:  # 图片块
                blocks.append(LayoutBlock(
                    bbox=tuple(block["bbox"]),
                    block_type=BlockType.FIGURE,
                    content="",
                    confidence=0.98,
                    reading_order=order,
                ))
                order += 1

        return blocks

    def _extract_font_info(self, line: dict) -> dict:
        """
        提取行级字体信息。
        返回最大字号、是否粗体、是否斜体。
        """
        max_size = 0.0
        is_bold = False
        is_italic = False

        for span in line.get("spans", []):
            size = span.get("size", 0)
            if size > max_size:
                max_size = size
            font_name = span.get("font", "").lower()
            if "bold" in font_name:
                is_bold = True
            if "italic" in font_name or "oblique" in font_name:
                is_italic = True
            # 检查 font flags
            flags = span.get("flags", 0)
            if flags & 2**1:  # bold
                is_bold = True
            if flags & 2**2:  # italic
                is_italic = True

        return {
            "max_size": max_size,
            "is_bold": is_bold,
            "is_italic": is_italic,
        }

    # ================================================================
    # 公式检测
    # ================================================================

    def _detect_formulas_in_layout(self, layout: list[LayoutBlock]):
        """
        在文本块中检测 LaTeX 公式。

        启发式规则：
          - $...$ 或 $$...$$ 包裹
          - 以 \begin{...} 开头
          - 字体为特殊的数学字体（如 Math, Symbol 等）
          - 文本中包含大量数学符号（\\frac, \\sum, \\int, \\alpha 等）
        """
        for block in layout:
            if block.block_type != BlockType.TEXT:
                continue

            # 检测显式公式分隔符
            if self._formula_pattern.search(block.content):
                block.block_type = BlockType.FORMULA
                continue

            # 检测纯 LaTeX 命令（块内容以 \ 开头且含数学命令）
            stripped = block.content.strip()
            if stripped.startswith("\\") and any(
                cmd in stripped for cmd in ["frac", "sum", "int", "alpha", "beta", "sqrt", "lim"]
            ):
                block.block_type = BlockType.FORMULA

    # ================================================================
    # 表格检测
    # ================================================================

    def _detect_tables_in_layout(self, page: fitz.Page, layout: list[LayoutBlock]):
        """
        检测页内表格并转为 Markdown。

        方法 1：使用 PyMuPDF 1.23+ 的 table detection
        方法 2：启发式 — 短文本行 + 对齐的列
        """
        try:
            tables = page.find_tables()
            if not tables:
                return

            for table in tables.tables:
                md_table = self._table_to_markdown(table)
                if not md_table:
                    continue

                # 找到表格范围的 LayoutBlock，替换
                table_bbox = table.bbox
                self._replace_blocks_with_table(layout, table_bbox, md_table)

        except (AttributeError, Exception):
            # find_tables 在某些 PyMuPDF 版本不可用，跳过
            pass

    def _table_to_markdown(self, table) -> str:
        """PyMuPDF Table → Markdown 文本"""
        try:
            data = table.extract()
            if not data:
                return ""

            lines = []
            for row_idx, row in enumerate(data):
                cells = [str(cell or "").replace("\n", " ").strip() for cell in row]
                lines.append("| " + " | ".join(cells) + " |")
                # 表头分隔行
                if row_idx == 0:
                    lines.append("| " + " | ".join("---" for _ in cells) + " |")

            return "\n".join(lines)
        except Exception:
            return ""

    def _replace_blocks_with_table(
        self, layout: list[LayoutBlock], table_bbox, md_table: str
    ):
        """在 layout 中用表格块替换对应区域的文本块"""
        new_layout = []
        replaced = False
        order = 0

        for block in layout:
            if not replaced and self._bboxes_overlap(block.bbox, table_bbox):
                new_layout.append(LayoutBlock(
                    bbox=tuple(table_bbox) if hasattr(table_bbox, '__iter__') else (0, 0, 0, 0),
                    block_type=BlockType.TABLE,
                    content=md_table,
                    confidence=0.90,
                    reading_order=order,
                ))
                order += 1
                replaced = True
                continue
            block.reading_order = order
            new_layout.append(block)
            order += 1

        layout[:] = new_layout

    # ================================================================
    # 标题识别
    # ================================================================

    def _mark_headings_in_layout(self, layout: list[LayoutBlock]):
        """
        基于文本模式标记标题。

        TODO: 后续版本利用 _extract_font_info 的字号/粗体信息提升准确度。
        """

        # 文本模式匹配
        heading_patterns = [
            re.compile(r"^第[一二三四五六七八九十\d]+章"),     # 第X章
            re.compile(r"^第[一二三四五六七八九十\d]+节"),     # 第X节
            re.compile(r"^\d+(\.\d+){0,2}\s+\S"),           # 1.1 xxx
            re.compile(r"^[一二三四五六七八九十]、"),          # 一、
            re.compile(r"^[（(][一二三四五六七八九十][)）]"),  # (一)
        ]

        for block in layout:
            if block.block_type != BlockType.TEXT:
                continue
            stripped = block.content.strip()
            if len(stripped) > 50:
                continue
            for pat in heading_patterns:
                if pat.match(stripped):
                    # 保持 BlockType.TEXT，但用特殊前缀标记（结构化阶段处理）
                    block.content = f"[HEADING] {stripped}"
                    break

    # ================================================================
    # 目录提取
    # ================================================================

    def _extract_toc(self, doc: fitz.Document) -> list[tuple[int, str, int]]:
        """
        提取 PDF 目录（Outline / Bookmarks）。

        返回: [(level, title, page_number), ...]
        """
        try:
            toc = doc.get_toc(simple=False)
            result = []
            for item in toc:
                level = item[0]
                title = item[1]
                page = item[2] if len(item) > 2 else -1
                result.append((level, title, page))
            return result
        except Exception:
            return []

    # ================================================================
    # 辅助方法
    # ================================================================

    def _bboxes_overlap(self, bbox1, bbox2) -> bool:
        """判断两个 bbox 是否有重叠"""
        try:
            x1_1, y1_1, x2_1, y2_1 = bbox1
            x1_2, y1_2, x2_2, y2_2 = bbox2
            return not (x2_1 < x1_2 or x2_2 < x1_1 or y2_1 < y1_2 or y2_2 < y1_1)
        except (TypeError, ValueError):
            return False

    def _crop_image_region(
        self, page: fitz.Page, bbox, page_no: int, idx: int
    ) -> Optional[bytes]:
        """裁剪页面指定区域为图片字节"""
        try:
            x1, y1, x2, y2 = bbox
            clip = fitz.Rect(x1, y1, x2, y2)
            mat = fitz.Matrix(self.render_dpi / 72, self.render_dpi / 72)
            pix = page.get_pixmap(matrix=mat, clip=clip)
            return pix.tobytes("png")
        except Exception as e:
            logger.warning(f"区域裁剪失败 p{page_no} idx{idx}: {e}")
            return None

    def _compute_layout_confidence(self, layout: list[LayoutBlock]) -> float:
        """计算 layout 平均置信度"""
        if not layout:
            return 0.98
        return round(
            sum(b.confidence for b in layout) / len(layout), 4
        )

    def extract_embedded_images(
        self, file_path: str, doc_uuid: str
    ) -> list[dict]:
        """
        提取 PDF 内嵌图片（如讲义中的截图、图表）。

        返回: [{"page_no": int, "image_index": int, "ext": str}]
        """
        doc = fitz.open(file_path)
        images = []
        img_dir = PAGE_IMAGES_DIR / doc_uuid / "embedded"
        img_dir.mkdir(parents=True, exist_ok=True)

        for page_no, page in enumerate(doc, start=1):
            for img_idx, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                base_image = doc.extract_image(xref)
                ext = base_image["ext"]
                filename = f"p{page_no:04d}_img{img_idx:02d}.{ext}"
                filepath = img_dir / filename
                filepath.write_bytes(base_image["image"])
                images.append({
                    "page_no": page_no,
                    "image_index": img_idx,
                    "ext": ext,
                    "path": f"pages/{doc_uuid}/embedded/{filename}",
                })

        doc.close()
        logger.info(f"提取 {len(images)} 张内嵌图片")
        return images


# ================================================================
# 便捷函数
# ================================================================

def parse_pdf(
    file_path: str,
    doc_uuid: str,
    ocr_provider: str = "paddle",
) -> list[PageResult]:
    """快速解析 PDF 的便捷函数"""
    ocr = create_ocr_engine(ocr_provider)
    parser = PDFParser(ocr_engine=ocr)
    return parser.parse(file_path, doc_uuid)
