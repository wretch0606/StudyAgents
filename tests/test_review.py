"""
低置信度复核测试
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/

from worker.ingestion.review import ReviewManager
from worker.schemas import (
    BlockType,
    ExamQuestion,
    LayoutBlock,
    PageResult,
    QuestionType,
    ReviewKind,
    ReviewStatus,
)


class TestReviewManager:
    """复核管理器"""

    def test_create_ocr_review(self):
        """低置信度 OCR 块 → 创建复核项"""
        mgr = ReviewManager(ocr_threshold=0.80)

        page = PageResult(
            page_no=1,
            text="",
            image_path="",
            layout=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20), block_type=BlockType.FORMULA,
                    content=r"E=mc^2", confidence=0.45, reading_order=0,
                ),
            ],
        )

        items = mgr.check_page(page)
        assert len(items) == 1
        assert items[0].kind == ReviewKind.OCR_FORMULA
        assert items[0].confidence == 0.45

    def test_high_confidence_no_review(self):
        """高置信度 → 不创建复核"""
        mgr = ReviewManager(ocr_threshold=0.80)

        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20), block_type=BlockType.TEXT,
                    content="正常文本", confidence=0.99, reading_order=0,
                ),
            ],
        )

        items = mgr.check_page(page)
        assert len(items) == 0

    def test_missing_answer_review(self):
        """无答案真题 → 复核项"""
        mgr = ReviewManager(answer_threshold=0.80)

        q = ExamQuestion(
            document_id="doc-1",
            question_no="5",
            question_type=QuestionType.CALCULATION,
            stem="推导薄膜干涉的光程差公式",
            confidence=0.3,
            answer_private="",
        )

        item = mgr.check_answer(q)
        assert item is not None
        assert item.kind == ReviewKind.MISSING_ANSWER

    def test_has_answer_no_review(self):
        """有答案高置信度 → 不创建复核"""
        mgr = ReviewManager()

        q = ExamQuestion(
            document_id="doc-1",
            question_no="1",
            question_type=QuestionType.CHOICE,
            stem="杨氏双缝实验...",
            answer_private="A",
            confidence=0.95,
        )

        item = mgr.check_answer(q)
        assert item is None

    def test_resolve_review(self):
        """处理复核项"""
        mgr = ReviewManager()

        # 先创建
        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20), block_type=BlockType.FORMULA,
                    content=r"\frac incorrect", confidence=0.32, reading_order=0,
                ),
            ],
        )
        items = mgr.check_page(page)
        rid = items[0].review_id

        # 处理
        ok = mgr.resolve(rid, reviewer_id="admin-001",
                         correction={"content": r"\frac{correct}"},
                         note="OCR 错误已修正")
        assert ok

        item = mgr.get_item(rid)
        assert item.status == ReviewStatus.RESOLVED
        assert item.correction["content"] == r"\frac{correct}"

    def test_dismiss_review(self):
        """驳回复核"""
        mgr = ReviewManager()

        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20), block_type=BlockType.TEXT,
                    content="正常", confidence=0.75, reading_order=0,
                ),
            ],
        )
        items = mgr.check_page(page)
        rid = items[0].review_id

        ok = mgr.dismiss(rid, "admin-001", "OCR 结果可接受")
        assert ok

        item = mgr.get_item(rid)
        assert item.status == ReviewStatus.DISMISSED

    def test_cannot_resolve_twice(self):
        """已处理的复核项不可重复处理"""
        mgr = ReviewManager()

        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20), block_type=BlockType.FORMULA,
                    content="x", confidence=0.5, reading_order=0,
                ),
            ],
        )
        items = mgr.check_page(page)
        rid = items[0].review_id

        mgr.resolve(rid, "admin-001")
        ok2 = mgr.resolve(rid, "admin-001")  # 第二次应失败
        assert not ok2

    def test_pending_filter(self):
        """待处理筛选"""
        mgr = ReviewManager()

        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20), block_type=BlockType.FORMULA,
                    content="a", confidence=0.3, reading_order=0,
                ),
                LayoutBlock(
                    bbox=(0, 20, 100, 40), block_type=BlockType.TEXT,
                    content="b", confidence=0.5, reading_order=1,
                ),
            ],
        )
        items = mgr.check_page(page)
        mgr.resolve(items[0].review_id, "admin-001")

        pending = mgr.get_pending()
        assert len(pending) == 1  # 只剩一个未处理

    def test_stats(self):
        """统计信息"""
        mgr = ReviewManager()

        page = PageResult(
            page_no=1, text="", image_path="",
            layout=[
                LayoutBlock(
                    bbox=(0, 0, 100, 20), block_type=BlockType.FORMULA,
                    content="x", confidence=0.3, reading_order=0,
                ),
            ],
        )
        items = mgr.check_page(page)
        mgr.resolve(items[0].review_id, "admin-001")

        stats = mgr.stats()
        assert stats["total"] == 1
        assert stats["resolved"] == 1
        assert stats["pending"] == 0
