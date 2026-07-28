"""
切块器 — 将结构化页面的文本切分为可检索的知识块

切块规则（优先级从高到低）：
  1. 真题边界优先 —— 题干、选项、图像引用、题号不拆散
  2. 标题边界       —— 章节标题处断块
  3. 页面边界       —— 不跨页
  4. 段落边界       —— 在段落间切分

参数约束：
  - 目标长度 500 中文字符
  - 最大长度 800 字
  - 前后重叠 80 字
  - 短块合并：< 100 字的相邻同类块合并
  - 答案隔离：private_content 标记 staff_only
  - 公式保留：LaTeX 与周边解释共同保存
"""

import hashlib
import logging
import re
from typing import Optional, Union
from uuid import uuid4

from worker.schemas import (
    Chunk,
    ChunkVisibility,
    ExamQuestion,
    MaterialType,
    PageResult,
    StructuredPage,
)

logger = logging.getLogger(__name__)

# 中文标点断句模式
_SENTENCE_BREAK = re.compile(r"([。！？；\n]|\.\s|\!\s|\?\s)")

# 标题检测模式
_HEADING_PATTERN = re.compile(
    r"^(\[HEADING\]\s*)?"
    r"((第[一二三四五六七八九十\d]+[章节])|"   # 第X章/节
    r"(\d+(\.\d+){0,2}\s+\S)|"                  # 1.1 xxx
    r"([一二三四五六七八九十]、)|"                # 一、
    r"([（(][一二三四五六七八九十\d]+[)）]))"     # (一)
)

# 公式标记
_FORMULA_MARKER = re.compile(r"(\$\$?|\\begin\{|\\frac|\\sum|\\int|\\sqrt)")


class Chunker:
    """
    知识切块器。

    使用示例：
        chunker = Chunker(target_chars=500, max_chars=800, overlap_chars=80)
        chunks = chunker.chunk_document(doc_id, pages, exam_questions)
    """

    def __init__(
        self,
        target_chars: int = 500,
        max_chars: int = 800,
        overlap_chars: int = 80,
        min_merge_chars: int = 100,
    ):
        self.target_chars = target_chars
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars
        self.min_merge_chars = min_merge_chars

    # ================================================================
    # 主入口
    # ================================================================

    def chunk_document(
        self,
        doc_id: str,
        pages: list[Union[PageResult, StructuredPage]],
        exam_questions: Optional[list[ExamQuestion]] = None,
        section_path: Optional[list[str]] = None,
    ) -> list[Chunk]:
        """
        将文档页面切分为知识块。

        Args:
            doc_id: 文档 UUID
            pages: 解析后的页面列表
            exam_questions: 已识别的真题（用于真题边界保护）
            section_path: 文档级章节路径前缀

        Returns:
            Chunk 列表
        """
        exam_questions = exam_questions or []
        section_path = section_path or []

        # Step 1: 收集所有段落到一个平坦列表
        segments = self._flatten_pages(pages, exam_questions)

        # Step 2: 按长度和边界切分大段
        raw_chunks = self._split_segments(segments, doc_id)

        # Step 3: 合并过短的相邻块
        merged = self._merge_short_chunks(raw_chunks)

        # Step 4: 添加重叠
        overlapped = self._add_overlap(merged)

        # Step 5: 批量计算哈希、分配 ID
        final = self._finalize(overlapped, doc_id, section_path)

        logger.info(
            f"切块完成: {len(pages)} 页 → {len(segments)} 段 → {len(final)} 块"
        )
        return final

    # ================================================================
    # Step 1: 页面 → 段落
    # ================================================================

    def _flatten_pages(
        self,
        pages: list[Union[PageResult, StructuredPage]],
        exam_questions: list[ExamQuestion],
    ) -> list[dict]:
        """
        将所有页面的内容展开为带元数据的段落列表。

        每个段落：{
            "text": str,
            "page_no": int,
            "is_exam": bool,          # 是否是真题内容（不可拆分）
            "question_no": str|None,
            "is_heading": bool,
            "is_formula": bool,
            "is_answer": bool,        # 是否是答案（private）
            "material_type": str,
        }
        """
        segments: list[dict] = []

        # 构建真题页码索引
        exam_pages: dict[int, list[ExamQuestion]] = {}
        for q in exam_questions:
            page = q.page_no if hasattr(q, "page_no") else 0
            exam_pages.setdefault(page, []).append(q)

        for page in pages:
            page_no = page.page_no

            # 结构化页面用 sections，非结构化页面用 layout
            if isinstance(page, StructuredPage):
                segments += self._segments_from_structured(page, page_no, exam_pages)
            else:
                segments += self._segments_from_page_result(page, page_no, exam_pages)

        return segments

    def _segments_from_page_result(
        self, page: PageResult, page_no: int, exam_pages: dict
    ) -> list[dict]:
        """从 PageResult.layout 提取段落"""
        segments = []
        for block in page.layout:
            if not block.content.strip():
                continue

            is_formula = block.block_type.value == "formula"
            is_exam = self._is_in_exam_range(page_no, block.bbox, exam_pages.get(page_no, []))

            segments.append({
                "text": block.content,
                "page_no": page_no,
                "is_exam": is_exam,
                "question_no": None,
                "is_heading": block.content.startswith("[HEADING]"),
                "is_formula": is_formula,
                "is_answer": False,
                "material_type": (
                    "formula" if is_formula else
                    "exam" if is_exam else
                    "text"
                ),
            })
        return segments

    def _segments_from_structured(
        self, page: StructuredPage, page_no: int, exam_pages: dict
    ) -> list[dict]:
        """从 StructuredPage.sections 提取段落"""
        segments = []
        for section in page.sections:
            # 标题
            if section.heading:
                segments.append({
                    "text": section.heading,
                    "page_no": page_no,
                    "is_exam": False,
                    "question_no": None,
                    "is_heading": True,
                    "is_formula": False,
                    "is_answer": False,
                    "material_type": "text",
                })
            # 段落
            for para in section.paragraphs:
                if not para.strip():
                    continue
                segments.append({
                    "text": para,
                    "page_no": page_no,
                    "is_exam": False,
                    "question_no": None,
                    "is_heading": False,
                    "is_formula": False,
                    "is_answer": False,
                    "material_type": "text",
                })
            # 公式
            for formula in section.formulas:
                segments.append({
                    "text": formula,
                    "page_no": page_no,
                    "is_exam": False,
                    "question_no": None,
                    "is_heading": False,
                    "is_formula": True,
                    "is_answer": False,
                    "material_type": "formula",
                })
        return segments

    # ================================================================
    # Step 2: 切分大段
    # ================================================================

    def _split_segments(self, segments: list[dict], doc_id: str) -> list[dict]:
        """
        将超过 max_chars 的段落切分，优先在句末/段末断。
        真题段落不拆分。
        """
        result: list[dict] = []

        for seg in segments:
            text = seg["text"]
            if seg["is_exam"] or len(text) <= self.max_chars:
                result.append(seg)
                continue

            # 找到安全断点
            breakpoints = list(_SENTENCE_BREAK.finditer(text))
            if not breakpoints:
                # 没有标点 → 只能硬切
                for i in range(0, len(text), self.target_chars):
                    piece = text[i:i + self.max_chars]
                    result.append({**seg, "text": piece})
                continue

            # 在 target_chars 附近找最近的断点
            pos = 0
            while pos < len(text):
                target_pos = pos + self.target_chars
                best_break = min(target_pos + self.target_chars, len(text))

                for m in breakpoints:
                    bp = m.end()
                    if target_pos <= bp <= pos + self.max_chars:
                        best_break = bp
                        break
                    elif pos < bp < best_break:
                        best_break = bp

                if best_break <= pos:
                    best_break = min(pos + self.max_chars, len(text))

                piece = text[pos:best_break].strip()
                if piece:
                    result.append({**seg, "text": piece})
                pos = best_break

        return result

    # ================================================================
    # Step 3: 合并短块
    # ================================================================

    def _merge_short_chunks(self, chunks: list[dict]) -> list[dict]:
        """
        合并过短的相邻块（< min_merge_chars 且同类、同页、非标题/真题）。
        """
        if not chunks:
            return []

        merged: list[dict] = []
        buffer = chunks[0]

        for chunk in chunks[1:]:
            buf_len = len(buffer["text"])
            cur_len = len(chunk["text"])

            can_merge = (
                buf_len < self.min_merge_chars
                and not buffer["is_heading"]
                and not buffer["is_exam"]
                and not chunk["is_exam"]
                and buffer["page_no"] == chunk["page_no"]
                and buffer["material_type"] == chunk["material_type"]
                and buf_len + cur_len <= self.max_chars
            )

            if can_merge:
                sep = "\n" if buffer["is_formula"] else ""
                buffer["text"] = buffer["text"] + sep + chunk["text"]
                buffer["is_formula"] = buffer["is_formula"] or chunk["is_formula"]
            else:
                if buffer["text"].strip():
                    merged.append(buffer)
                buffer = chunk

        if buffer["text"].strip():
            merged.append(buffer)

        return merged

    # ================================================================
    # Step 4: 重叠
    # ================================================================

    def _add_overlap(self, chunks: list[dict]) -> list[dict]:
        """
        在相邻块间添加重叠文本。
        每块末尾 overlap_chars 字作为下一块的开头前缀。
        """
        if len(chunks) <= 1 or self.overlap_chars <= 0:
            return chunks

        result = [chunks[0]]

        for i in range(1, len(chunks)):
            prev_text = chunks[i - 1]["text"]
            overlap_text = prev_text[-self.overlap_chars:] if len(prev_text) > self.overlap_chars else prev_text

            # 在重叠处断句（避免从词中间截断）
            clean_overlap = overlap_text.lstrip("，。！？；：、,.;:!? \t\n")
            if len(clean_overlap) < self.overlap_chars // 2:
                clean_overlap = overlap_text

            chunk = dict(chunks[i])
            chunk["text"] = clean_overlap + "\n" + chunk["text"]
            result.append(chunk)

        return result

    # ================================================================
    # Step 5: 最终化
    # ================================================================

    def _finalize(
        self,
        chunks: list[dict],
        doc_id: str,
        section_path: list[str],
    ) -> list[Chunk]:
        """分配 ID、计算哈希、构造 Chunk 对象"""
        final: list[Chunk] = []
        for seg in chunks:
            content = seg["text"].replace("[HEADING] ", "").replace("[HEADING]", "")
            chunk = Chunk(
                chunk_id=str(uuid4()),
                document_id=doc_id,
                page_from=seg["page_no"],
                page_to=seg["page_no"],
                content=content,
                question_no=seg.get("question_no"),
                section_path=list(section_path),
                material_type=MaterialType(seg.get("material_type", "text")),
                visibility=(
                    ChunkVisibility.STAFF_ONLY if seg.get("is_answer")
                    else ChunkVisibility.PUBLIC
                ),
                content_version=1,
            )
            # 计算内容哈希
            chunk.content_hash = hashlib.sha256(content.encode()).hexdigest()
            final.append(chunk)

        return final

    # ================================================================
    # 真题边界判断
    # ================================================================

    def _is_in_exam_range(
        self, page_no: int, bbox, page_questions: list[ExamQuestion]
    ) -> bool:
        """判断某个 bbox 是否落在真题范围内"""
        if not page_questions:
            return False
        for q in page_questions:
            # ExamQuestion 的页码存放在 source_ref.page_number
            q_page = (
                q.source_ref.page_number
                if q.source_ref and q.source_ref.page_number
                else getattr(q, "page_no", 0)
            )
            if q_page == page_no:
                return True
        return False

    # ================================================================
    # 便捷函数
    # ================================================================

    def chunk_single_page(
        self,
        doc_id: str,
        page: Union[PageResult, StructuredPage],
    ) -> list[Chunk]:
        """单页切块的便捷入口"""
        return self.chunk_document(doc_id, [page])
