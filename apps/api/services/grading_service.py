"""GradingService — 答案提交、评分编排、幂等、掌握度更新。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.answer_submission import AnswerSubmission
from apps.api.db.models.grade_result import GradeResult
from apps.api.db.models.idempotency import IdempotencyRecord
from apps.api.db.models.mastery_change_log import MasteryChangeLog
from apps.api.db.models.mastery_record import MasteryRecord
from apps.api.db.models.practice_item import PracticeItem
from apps.api.db.models.wrong_book_entry import WrongBookEntry
from apps.api.schemas.grading import SubmitAnswerResponse


class GradingService:
    """答案提交与评分服务。

    幂等：X-Idempotency-Key 确保同键重放返回缓存结果。
    并发安全：FOR UPDATE 锁防止并发重复评分。
    事务：全部操作在同一事务中，异常时回滚。
    """

    _SCOPE = "answer_submission"

    def __init__(self, session: AsyncSession, *, adapter=None):
        self._session = session
        self._adapter = adapter or _default_adapter()

    async def submit_answer(
        self,
        *,
        session_id: str,
        item_id: str,
        user_id: str,
        answer_text: str,
        question_version: str,
        idempotency_key: str,
    ) -> SubmitAnswerResponse:
        """提交答案并评分。

        1. 幂等检查
        2. 验证题目属于当前训练 + owner + version
        3. FOR UPDATE 锁 idempotency 行（并发保护）
        4. 插入 AnswerSubmission
        5. 调用 C 评分
        6. 写入 GradeResult
        7. 更新 MasteryRecord
        8. 创建 WrongBookEntry
        9. 标记幂等完成
        """
        # ---- 1. 幂等检查 ----
        cached = await self._session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.scope == self._SCOPE,
                IdempotencyRecord.idempotency_key == idempotency_key,
            ).with_for_update(),
        )
        idem = cached.scalar_one_or_none()

        if idem is not None and idem.status == "completed":
            if idem.response_json:
                return SubmitAnswerResponse(**idem.response_json)
            raise GradingError(
                code="GRADING_FAILED",
                message="先前的提交处理失败，请使用新的幂等键重试。",
                retryable=True,
            )

        if idem is not None and idem.status == "processing":
            raise GradingError(
                code="GRADING_IN_PROGRESS",
                message="评分正在处理中，请稍后重试。",
                retryable=True,
            )

        # 创建或重用幂等记录
        fingerprint = _fingerprint(user_id, item_id, answer_text)
        if idem is None:
            idem = IdempotencyRecord(
                user_id=user_id,
                scope=self._SCOPE,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                status="processing",
            )
            self._session.add(idem)
            await self._session.flush()
        else:
            idem.status = "processing"
            idem.request_fingerprint = fingerprint
            idem.retry_count += 1
            await self._session.flush()

        # ---- 2. 验证题目 ----
        item = await self._session.execute(
            select(PracticeItem).where(
                PracticeItem.id == item_id,
                PracticeItem.session_id == session_id,
                PracticeItem.user_id == user_id,
            ),
        )
        item = item.scalar_one_or_none()
        if item is None:
            raise GradingError(
                code="RESOURCE_NOT_FOUND",
                message="题目不属于当前训练。",
                retryable=False,
            )
        if item.question_version != question_version:
            raise GradingError(
                code="VERSION_MISMATCH",
                message=f"题目版本不匹配：期望 {item.question_version}，收到 {question_version}",
                retryable=False,
            )

        # ---- 3. 检查已有提交 ----
        existing = await self._session.execute(
            select(AnswerSubmission).where(
                AnswerSubmission.item_id == item_id,
            ).order_by(AnswerSubmission.attempt.desc()).limit(1),
        )
        existing = existing.scalar_one_or_none()

        if existing is not None:
            # 已有提交 → 检查是否已评分
            existing_grade = await self._session.execute(
                select(GradeResult).where(
                    GradeResult.submission_id == existing.id,
                ),
            )
            if existing_grade.scalar_one_or_none() is not None:
                raise GradingError(
                    code="ALREADY_GRADED",
                    message="该题已提交并评分。",
                    retryable=False,
                )

        # ---- 4. 插入 AnswerSubmission ----
        attempt = (existing.attempt + 1) if existing else 1
        submission = AnswerSubmission(
            item_id=item_id,
            user_id=user_id,
            attempt=attempt,
            answer_text=answer_text,
            submitted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._session.add(submission)
        await self._session.flush()

        # ---- 5. 调用 C 评分 ----
        rubric = (item.private_snapshot or {}).get("private", {}).get("rubric", [])
        expected = (item.private_snapshot or {}).get("private", {}).get("expected_answer", "")

        try:
            result = await self._adapter.grade(
                item_id=item_id,
                user_answer=answer_text,
                rubric=rubric,
                expected_answer=expected,
            )
        except Exception:
            idem.status = "failed"
            await self._session.flush()
            raise GradingError(
                code="GRADING_FAILED",
                message="评分服务内部错误，请重试。",
                retryable=True,
            )

        # ---- 6. 写入 GradeResult ----
        review_required = result.get("review_required", False)
        grade = GradeResult(
            submission_id=submission.id,
            user_id=user_id,
            total_score=result["score"],
            step_scores=result.get("step_scores"),
            confidence=result.get("confidence", 0.0),
            review_required=review_required,
            public_feedback=_build_feedback(result),
        )
        self._session.add(grade)
        await self._session.flush()

        # ---- 7. 更新 MasteryRecord ----
        knowledge_point = (item.public_snapshot or {}).get("source_kind", "practice")
        mastery = await self._get_or_create_mastery(user_id, knowledge_point)

        before_level = mastery.current_level
        before_streak = mastery.streak
        max_score = result.get("max_score", 10)
        score = result.get("score", 0)
        is_correct = score >= max_score * 0.6

        mastery.total_attempts += 1
        mastery.last_practiced_at = datetime.now(UTC).replace(tzinfo=None)
        if is_correct:
            mastery.total_correct += 1
            mastery.streak += 1
        else:
            mastery.streak = 0
        mastery.current_level = round(
            mastery.total_correct / max(mastery.total_attempts, 1), 2,
        )
        await self._session.flush()

        # 记录变更
        self._session.add(MasteryChangeLog(
            mastery_id=mastery.id,
            user_id=user_id,
            change_reason="grade_result" if is_correct else "wrong_answer",
            source_grade_id=grade.id,
            before_level=before_level,
            after_level=mastery.current_level,
            before_streak=before_streak,
            after_streak=mastery.streak,
        ))

        # ---- 8. 创建 WrongBookEntry（如果答错） ----
        wrong_book_created = False
        if not is_correct:
            correct_answer = expected or result.get("explanation", "")
            entry = WrongBookEntry(
                user_id=user_id,
                item_id=item_id,
                submission_id=submission.id,
                grade_id=grade.id,
                question_type=item.question_type,
                stem_snapshot=item.stem,
                wrong_answer=answer_text,
                correct_answer=str(correct_answer)[:5000] if correct_answer else None,
            )
            self._session.add(entry)
            wrong_book_created = True

        # ---- 9. 标记幂等完成 ----
        response_data = SubmitAnswerResponse(
            submission_id=str(submission.id),
            grade_id=str(grade.id),
            score=score,
            max_score=max_score,
            score_ratio=round(score / max(max_score, 1), 2),
            verdict=_verdict(score, max_score),
            summary=_build_feedback(result),
            step_feedback=_step_feedback_strings(result.get("step_scores", [])),
            confidence=result.get("confidence", 0.0),
            review_required=review_required,
            wrong_book_created=wrong_book_created,
        )
        idem.status = "completed"
        idem.response_json = response_data.model_dump()

        await self._session.commit()
        return response_data

    async def _get_or_create_mastery(self, user_id: str, kp: str) -> MasteryRecord:
        result = await self._session.execute(
            select(MasteryRecord).where(
                MasteryRecord.user_id == user_id,
                MasteryRecord.knowledge_point == kp,
            ),
        )
        m = result.scalar_one_or_none()
        if m is None:
            m = MasteryRecord(user_id=user_id, knowledge_point=kp)
            self._session.add(m)
            await self._session.flush()
        return m


# ---- Error ----

class GradingError(Exception):
    def __init__(self, *, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# ---- Helpers ----

def _fingerprint(user_id: str, item_id: str, answer: str) -> str:
    h = hashlib.sha256(f"{user_id}:{item_id}:{answer}".encode()).hexdigest()
    return h[:32]


def _verdict(score: float, max_score: float) -> str:
    if max_score == 0:
        return "未评分"
    ratio = score / max_score
    if ratio >= 0.9:
        return "优秀"
    if ratio >= 0.7:
        return "良好"
    if ratio >= 0.5:
        return "需改进"
    return "需复习"


def _build_feedback(result: dict) -> str:
    score = result.get("score", 0)
    max_s = result.get("max_score", 10)
    return f"得分: {score}/{max_s}"


def _step_feedback_strings(step_scores: list[dict]) -> list[str]:
    return [s.get("feedback", "") for s in step_scores]


# ---- Default adapter ----

_default = None


def _default_adapter():
    global _default
    if _default is None:
        from apps.api.services.grading_adapter import FakeGradingAdapter
        _default = FakeGradingAdapter()
    return _default
