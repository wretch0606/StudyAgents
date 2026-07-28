"""
真题识别与结构化

从解析结果中提取：题号、题型、题干、选项、分值、答案、知识点。

检测策略：
  1. 题号模式：数字+标点、中文序号、括号数字
  2. 题型判断：选项字母、填空下划线、计算/简答关键词
  3. 答案提取：答案标记 + 分值标记
  4. 无答案真题 → 标记低置信度
"""

import logging
import re
from typing import Optional

from worker.schemas import (
    ExamQuestion,
    Option,
    PageResult,
    QuestionType,
    RubricItem,
    SourceRef,
    StructuredPage,
)

logger = logging.getLogger(__name__)

# ---- 题号检测模式 ----

_QUESTION_START = re.compile(
    r"^\s*"
    r"("
    r"\d+\.\(\d+\)\s*"                 # 3.(1) / 3.(2) 子题号
    r"|"
    r"\d+[.、．)\s]"                    # 1. / 1、/ 1) / 1．
    r"|"
    r"[（(]\d+[)）]\s*"                 # (1) / （1）
    r"|"
    r"[一二三四五六七八九十]+[、．]\s*"   # 一、/ 二、
    r"|"
    r"[（(][一二三四五六七八九十]+[)）]"  # (一) / (二)
    r")"
)

# 题号提取（含子题号 3.(1)）
_QUESTION_NO = re.compile(r"(\d+(?:\.\(\d+\))?(?:\.\d+)*|[一二三四五六七八九十]+)")

# ---- 题型判断模式 ----

_CHOICE_OPTION = re.compile(r"[A-D][.、．\)]\s*\S")      # A. xxx
_FILL_BLANK = re.compile(r"[_＿]{2,}|（\s*）|\(\s*\)")   # ___ / （）
_CALC_KEYWORDS = {"计算", "求解", "求", "推导", "证明", "算出", "试求"}
_SHORT_KEYWORDS = {"简述", "说明", "解释", "分析", "比较", "讨论", "论述", "什么是", "试述"}

# ---- 答案/分值标记 ----

_ANSWER_MARKER = re.compile(
    r"(答案|参考答案|标准答案|正确选项)[：:：\s]*([^\n]{0,200})"
)
_SCORE_MARKER = re.compile(r"[（(](\d+)\s*分[)）]|(\d+)\s*分")
_KNOWLEDGE_HINT = re.compile(r"知识点[：:：\s]*(\S+)")


class ExamExtractor:
    """真题识别器"""

    def __init__(self):
        self._seen_numbers: set[str] = set()  # 已见题号（去重）

    def extract(
        self,
        doc_id: str,
        pages: list[PageResult],
        structured_pages: Optional[list[StructuredPage]] = None,
    ) -> list[ExamQuestion]:
        """
        从页面中提取结构化真题。

        Args:
            doc_id: 文档 UUID
            pages: 解析后的页面
            structured_pages: 结构化页面（可选，用于 section 上下文）

        Returns:
            ExamQuestion 列表
        """
        self._seen_numbers.clear()
        questions: list[ExamQuestion] = []

        for page in pages:
            # 逐段扫描
            segments = self._page_segments(page)

            i = 0
            while i < len(segments):
                seg = segments[i]
                match = _QUESTION_START.match(seg)
                if not match:
                    i += 1
                    continue

                # 提取题号
                no_match = _QUESTION_NO.search(match.group())
                question_no = no_match.group() if no_match else str(len(questions) + 1)

                # 跳过已见过的题号
                key = f"{page.page_no}-{question_no}"
                if key in self._seen_numbers:
                    i += 1
                    continue
                self._seen_numbers.add(key)

                # 收集题目内容（直到下一题或页面结束）
                stem_parts = [seg[len(match.group()):].strip()]
                i += 1
                while i < len(segments) and not _QUESTION_START.match(segments[i]):
                    stem_parts.append(segments[i])
                    i += 1

                stem = "\n".join(stem_parts).strip()
                if not stem:
                    continue

                # 判断题型
                q_type = self._identify_type(stem)

                # 提取选项
                options = self._extract_options(stem) if q_type == QuestionType.CHOICE else []

                # 如果有选项，题干中去掉选项部分
                clean_stem = self._clean_stem(stem)

                # 提取答案
                answer, answer_conf = self._extract_answer(stem)

                # 提取分值
                max_score = self._extract_score(stem)

                # 提取知识点
                kp_ids = self._extract_knowledge_hints(stem)

                # 构建 SourceRef
                source_ref = SourceRef(
                    document_id=doc_id,
                    document_name="",
                    page_number=page.page_no,
                    question_no=question_no,
                    excerpt=clean_stem[:200],
                )

                questions.append(ExamQuestion(
                    document_id=doc_id,
                    question_no=question_no,
                    question_type=q_type,
                    stem=clean_stem,
                    options=options,
                    max_score=max_score,
                    answer_private=answer,
                    knowledge_point_ids=kp_ids,
                    source_ref=source_ref,
                    confidence=answer_conf,
                    answer_origin="original" if answer_conf >= 0.8 else "unknown",
                ))

        logger.info(f"真题识别: {len(questions)} 题, "
                    f"类型分布: {self._type_distribution(questions)}")
        return questions

    # ---- 题型判断 ----

    def _identify_type(self, text: str) -> QuestionType:
        """根据文本特征判断题型"""
        # 选择题：有 A/B/C/D 选项
        if _CHOICE_OPTION.search(text):
            return QuestionType.CHOICE

        # 填空题：有下划线或空括号
        if _FILL_BLANK.search(text):
            return QuestionType.FILL_BLANK

        # 计算题：含计算关键词
        if any(kw in text for kw in _CALC_KEYWORDS):
            return QuestionType.CALCULATION

        # 简答题：含简答关键词
        if any(kw in text for kw in _SHORT_KEYWORDS):
            return QuestionType.SHORT_ANSWER

        # 默认：有选项→选择，有填空→填空，否则简答
        return QuestionType.SHORT_ANSWER

    # ---- 选项提取 ----

    def _extract_options(self, text: str) -> list[Option]:
        """提取选择题选项 A. xxx / B. xxx"""
        options = []
        for m in re.finditer(r"([A-D])[.、．\)]\s*(.+?)(?=\s*[A-D][.、．\)]|\s*$)", text, re.DOTALL):
            options.append(Option(id=m.group(1), text=m.group(2).strip()[:200]))
        return options

    # ---- 题干清理 ----

    def _clean_stem(self, text: str) -> str:
        """去掉选项部分，保留纯净题干"""
        # 找到第一个选项的位置
        opt_match = _CHOICE_OPTION.search(text)
        if opt_match:
            text = text[:opt_match.start()].strip()
        # 去掉答案标记
        text = _ANSWER_MARKER.sub("", text)
        return text.strip()

    # ---- 答案提取 ----

    def _extract_answer(self, text: str) -> tuple[str, float]:
        """提取答案文本和置信度"""
        m = _ANSWER_MARKER.search(text)
        if m:
            answer = m.group(2).strip()
            # 有答案标记 → 高置信度
            return answer, 0.95
        return "", 0.3  # 无答案标记 → 低置信度

    # ---- 分值提取 ----

    def _extract_score(self, text: str) -> Optional[float]:
        """提取分值"""
        m = _SCORE_MARKER.search(text)
        if m:
            return float(m.group(1) or m.group(2))
        return None

    # ---- 知识点提示 ----

    def _extract_knowledge_hints(self, text: str) -> list[str]:
        """提取知识点提示（供后续匹配知识点 ID）"""
        hints = []
        for m in _KNOWLEDGE_HINT.finditer(text):
            hints.append(m.group(1))
        return hints

    # ---- 工具 ----

    @staticmethod
    def _page_segments(page: PageResult) -> list[str]:
        """将页面 layout 展开为文本段列表"""
        return [block.content for block in page.layout if block.content.strip()]

    @staticmethod
    def _type_distribution(questions: list[ExamQuestion]) -> dict:
        dist: dict[str, int] = {}
        for q in questions:
            t = q.question_type.value
            dist[t] = dist.get(t, 0) + 1
        return dist

    def reset(self):
        """重置状态"""
        self._seen_numbers.clear()
