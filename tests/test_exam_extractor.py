"""
真题识别器测试
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from worker.ingestion.exam_extractor import ExamExtractor
from worker.schemas import (
    BlockType,
    LayoutBlock,
    PageResult,
    QuestionType,
)


def _make_page(blocks: list[str]) -> PageResult:
    """构造含真题文本的页面"""
    layout = [
        LayoutBlock(
            bbox=(0, i * 20, 400, i * 20 + 18),
            block_type=BlockType.TEXT,
            content=text,
            confidence=1.0,
            reading_order=i,
        )
        for i, text in enumerate(blocks)
    ]
    return PageResult(
        page_no=1,
        text="\n".join(blocks),
        image_path="",
        layout=layout,
        is_digital=True,
    )


class TestExamExtractor:
    """真题识别"""

    def test_choice_question(self):
        """识别单选题"""
        page = _make_page([
            "1. 杨氏双缝实验中，相邻明条纹间距公式为：",
            "A. Δx=λD/d",
            "B. Δx=d/λD",
            "C. Δx=λd/D",
            "D. Δx=D/λd",
            "答案：A",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])

        assert len(questions) == 1
        q = questions[0]
        assert q.question_type == QuestionType.CHOICE
        assert q.question_no == "1"
        assert len(q.options) >= 3  # 至少识别出 A/B/C
        assert q.answer_private == "A"
        assert q.confidence >= 0.8

    def test_fill_blank(self):
        """识别填空题"""
        page = _make_page([
            "2. 两列光波产生干涉的必要条件是具有相同的______、相同的______和固定的______。",
            "答案：频率 振动方向 相位差",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])

        assert len(questions) == 1
        assert questions[0].question_type == QuestionType.FILL_BLANK
        assert "______" in questions[0].stem  # 填空下划线是题干的一部分

    def test_calculation_question(self):
        """识别计算题"""
        page = _make_page([
            "3. 计算：在杨氏双缝实验中，d=0.5mm，D=1.5m，λ=600nm，求相邻明条纹间距Δx。（10分）",
            "答案：Δx=λD/d=1.8mm",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])

        assert len(questions) == 1
        assert questions[0].question_type == QuestionType.CALCULATION
        assert questions[0].max_score == 10.0

    def test_short_answer(self):
        """识别简答题"""
        page = _make_page([
            "4. 简述等倾干涉和等厚干涉的区别。",
            "答案：等倾干涉薄膜厚度均匀，条纹定域于无穷远；"
            "等厚干涉薄膜厚度变化，条纹定域于薄膜表面附近。",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])

        assert len(questions) == 1
        assert questions[0].question_type == QuestionType.SHORT_ANSWER

    def test_multi_questions(self):
        """一页多题"""
        page = _make_page([
            "1. 光干涉的必要条件是？",
            "A. 相同频率 B. 相同振幅 C. 相同波长 D. 以上都是",
            "答案：A",
            "2. 杨氏双缝实验属于_____干涉。（分波前/分振幅）",
            "答案：分波前",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])
        assert len(questions) == 2

    def test_missing_answer_low_confidence(self):
        """无答案 → 低置信度"""
        page = _make_page([
            "5. 推导薄膜干涉的光程差公式。",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])

        assert len(questions) == 1
        assert questions[0].confidence < 0.8
        assert questions[0].answer_private == ""

    def test_chinese_number_question(self):
        """中文序号题"""
        page = _make_page([
            "一、光的干涉条件是什么？",
            "答案：相同频率、相同振动方向、固定相位差。",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])

        assert len(questions) >= 1
        assert "干涉条件" in questions[0].stem

    def test_empty_page(self):
        """空页面 → 无真题"""
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [])
        assert questions == []

    def test_score_extraction(self):
        """分值提取"""
        page = _make_page([
            "6. 计算光程差。（8分）",
            "答案：δ=2nd cosθ",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])

        assert len(questions) == 1
        assert questions[0].max_score == 8.0

    def test_duplicate_detection(self):
        """重复题号去重"""
        page = _make_page([
            "1. 第一问", "1. 重复的第一问",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])
        assert len(questions) == 1  # 只保留第一个

    def test_sub_question_number(self):
        """子题号 3.(1) / 3.(2) 分别识别为独立题目"""
        page = _make_page([
            "3.(1) 简述牛顿环的形成原理。（5分）",
            "答案：...",
            "3.(2) 推导牛顿环半径公式 r_k=√(kλR)。（10分）",
            "答案：...",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])
        assert len(questions) == 2
        assert questions[0].question_no.startswith("3")
        assert questions[1].question_no.startswith("3")

    def test_numbered_list_not_question(self):
        """编号列表不一定是真题"""
        page = _make_page([
            "以下是一些注意事项：",
            "1. 实验前需校准仪器",
            "2. 数据记录需保留三位有效数字",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])
        # 可能是 0 或 2（取决于检测灵敏度），但不应崩溃
        assert isinstance(questions, list)

    def test_mixed_question_types_page(self):
        """一页混合多种题型"""
        page = _make_page([
            "一、选择题（每题 3 分）",
            "1. 光干涉的必要条件是？ A. 相同频率 B. 相同波长 C. 相同振幅 D. 以上都是",
            "答案：A",
            "二、填空题（每题 4 分）",
            "2. 杨氏双缝实验属于______干涉。",
            "答案：分波前",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])
        assert len(questions) >= 2
        types = {q.question_type.value for q in questions}
        assert "choice" in types
        assert "fill_blank" in types

    def test_cross_page_question(self):
        """跨页真题：题干在第 1 页，选项在第 2 页"""
        page1 = _make_page([
            "1. 下列关于光的干涉的说法，正确的是：",
        ])
        page2 = _make_page([
            "A. 任何两列光波都能产生干涉",
            "B. 只有相干光才能产生干涉",
            "C. 干涉条纹与波长无关",
            "D. 以上说法都不正确",
            "答案：B",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page1, page2])
        assert len(questions) >= 1

    def test_pure_text_no_questions(self):
        """纯讲义页（无真题）不误判"""
        page = _make_page([
            "两列光波在空间相遇时，若满足相干条件，则会产生干涉现象。",
            "相干条件包括：相同频率、相同振动方向、固定相位差。",
            "杨氏双缝干涉实验是分波前法的典型代表。",
        ])
        extractor = ExamExtractor()
        questions = extractor.extract("doc-1", [page])
        assert len(questions) == 0  # 无题号的行不应被识别为真题

    def test_reset_clears_seen(self):
        """reset() 清除已见题号"""
        page = _make_page(["1. 一题", "答案：..."])
        extractor = ExamExtractor()
        q1 = extractor.extract("doc-1", [page])
        assert len(q1) == 1

        extractor.reset()
        q2 = extractor.extract("doc-1", [page])
        assert len(q2) == 1  # reset 后应重新识别


class TestIntegration:
    """与解析结果集成"""

    def test_extract_from_parsed_pdf(self):
        """从样例 PDF 解析结果中提取真题"""
        from worker.ingestion.parsers.pdf import PDFParser
        from worker.ingestion.parsers.ocr import MockOCRAdapter

        sample = Path(__file__).resolve().parent / "fixtures" / "sample_lecture.pdf"
        if not sample.exists():
            pytest.skip("样例 PDF 不存在")

        parser = PDFParser(ocr_engine=MockOCRAdapter())
        pages = parser.parse(str(sample), "test-uuid")

        extractor = ExamExtractor()
        questions = extractor.extract("test-uuid", pages)

        # 样例 PDF 第 1 页不含显式真题，结果可能为 0
        # 但不应崩溃
        assert isinstance(questions, list)
