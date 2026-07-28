"""
低置信度复核管理

负责：
  1. OCR 公式/文字块复核项创建
  2. 无标准答案真题复核项创建
  3. 复核项查询、修正、驳回
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from worker.schemas import (
    ExamQuestion,
    PageResult,
    ReviewItem,
    ReviewKind,
    ReviewStatus,
)

logger = logging.getLogger(__name__)


class ReviewManager:
    """低置信度复核管理器"""

    def __init__(self, ocr_threshold: float = 0.80, answer_threshold: float = 0.80):
        self.ocr_threshold = ocr_threshold
        self.answer_threshold = answer_threshold

        # 内存存储（生产应替为 DB）
        self._items: dict[str, ReviewItem] = {}

    # ================================================================
    # 创建复核项
    # ================================================================

    def check_page(self, page: PageResult) -> list[ReviewItem]:
        """
        检查页面 OCR 质量，创建低置信度复核项。

        触发条件：
          - 公式块置信度 < ocr_threshold
          - 文本块置信度 < ocr_threshold
          - 页面整体置信度 < ocr_threshold
        """
        items: list[ReviewItem] = []

        for block in page.layout:
            if block.confidence >= self.ocr_threshold:
                continue

            if block.block_type.value == "formula":
                kind = ReviewKind.OCR_FORMULA
            else:
                kind = ReviewKind.OCR_TEXT

            item = ReviewItem(
                review_id=str(uuid4()),
                kind=kind,
                target_type="document_page",
                target_id=f"page-{page.page_no}",
                confidence=block.confidence,
                payload={
                    "page_no": page.page_no,
                    "block_content": block.content,
                    "bbox": list(block.bbox),
                    "block_type": block.block_type.value,
                },
            )
            self._items[item.review_id] = item
            items.append(item)

        if items:
            logger.info(f"页 {page.page_no}: {len(items)} 个低置信度复核项")

        return items

    def check_answer(self, question: ExamQuestion) -> Optional[ReviewItem]:
        """
        检查真题答案质量。

        触发条件：
          - 无标准答案（answer_private 为空）
          - 答案置信度 < answer_threshold
        """
        if question.answer_private and question.confidence >= self.answer_threshold:
            return None

        kind = ReviewKind.MISSING_ANSWER if not question.answer_private else ReviewKind.LOW_CONFIDENCE

        item = ReviewItem(
            review_id=str(uuid4()),
            kind=kind,
            target_type="exam_question",
            target_id=question.question_no,
            confidence=question.confidence,
            payload={
                "question_no": question.question_no,
                "question_type": question.question_type.value,
                "stem_preview": question.stem[:200],
                "has_answer": bool(question.answer_private),
                "answer_origin": question.answer_origin,
            },
        )
        self._items[item.review_id] = item

        logger.info(f"题 {question.question_no}: 答案复核项 (kind={kind.value})")
        return item

    # ================================================================
    # 查询
    # ================================================================

    def get_pending(self, kind: Optional[ReviewKind] = None) -> list[ReviewItem]:
        """获取待处理复核项"""
        items = [
            i for i in self._items.values()
            if i.status == ReviewStatus.PENDING
        ]
        if kind:
            items = [i for i in items if i.kind == kind]
        return sorted(items, key=lambda i: i.confidence)

    def get_item(self, review_id: str) -> Optional[ReviewItem]:
        """获取单个复核项"""
        return self._items.get(review_id)

    # ================================================================
    # 处理
    # ================================================================

    def resolve(
        self,
        review_id: str,
        reviewer_id: str,
        correction: Optional[dict] = None,
        note: str = "",
    ) -> bool:
        """
        处理复核项。

        Args:
            review_id: 复核项 ID
            reviewer_id: 处理人 ID（管理员）
            correction: 修正数据（如 OCR 修正文本）
            note: 处理说明

        Returns:
            True 表示处理成功
        """
        item = self._items.get(review_id)
        if item is None:
            logger.warning(f"复核项不存在: {review_id}")
            return False

        if item.status != ReviewStatus.PENDING:
            logger.warning(f"复核项已处理: {review_id} (status={item.status.value})")
            return False

        item.status = ReviewStatus.RESOLVED
        item.resolution = note
        item.correction = correction
        item.reviewer_id = reviewer_id

        # 更新 payload（合并修正）
        if correction:
            item.payload = {**item.payload, "corrected": correction}

        item.resolved_at = datetime.now(timezone.utc).isoformat()

        logger.info(f"复核项 {review_id} 已处理 by {reviewer_id}")
        return True

    def dismiss(
        self,
        review_id: str,
        reviewer_id: str,
        note: str = "",
    ) -> bool:
        """驳回复核项（无需修正）"""
        item = self._items.get(review_id)
        if item is None:
            return False

        item.status = ReviewStatus.DISMISSED
        item.resolution = note
        item.reviewer_id = reviewer_id
        item.resolved_at = datetime.now(timezone.utc).isoformat()

        logger.info(f"复核项 {review_id} 已驳回 by {reviewer_id}")
        return True

    # ================================================================
    # 统计
    # ================================================================

    @property
    def pending_count(self) -> int:
        return len(self.get_pending())

    def stats(self) -> dict:
        """复核统计"""
        total = len(self._items)
        pending = sum(1 for i in self._items.values() if i.status == ReviewStatus.PENDING)
        resolved = sum(1 for i in self._items.values() if i.status == ReviewStatus.RESOLVED)
        dismissed = sum(1 for i in self._items.values() if i.status == ReviewStatus.DISMISSED)

        by_kind = {}
        for i in self._items.values():
            k = i.kind.value
            by_kind[k] = by_kind.get(k, 0) + 1

        return {
            "total": total,
            "pending": pending,
            "resolved": resolved,
            "dismissed": dismissed,
            "by_kind": by_kind,
        }
