"""TrainingService — 训练创建和下一题编排。"""

from __future__ import annotations

import uuid as _uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.repositories import practice as repo
from apps.api.schemas.training import NextQuestionResponse


class TrainingService:
    """训练服务 — 会话创建、题目生成、下一题获取。

    属主隔离：所有操作强制 user_id。
    并发安全：同一 session 的"下一题"幂等返回当前题。
    """

    def __init__(self, session: AsyncSession, *, adapter=None):
        self._session = session
        self._adapter = adapter or _default_adapter()

    # ---- Create ----

    async def create_training(
        self,
        *,
        user_id: str,
        chapter_ids: list[str] | None = None,
        question_types: list[str] | None = None,
        difficulty: int = 2,
        count: int = 5,
    ) -> dict:
        """创建训练会话并生成所有题目。

        返回: {session_id, thread_id, total_questions}
        若证据不足（< 3 题），raise TrainingError。
        """
        sid = str(_uuid.uuid4())
        tid = str(_uuid.uuid4())

        await repo.create_practice_session(
            self._session, session_id=sid, user_id=user_id, thread_id=tid,
            filters={
                "chapter_ids": chapter_ids or [],
                "question_types": question_types or ["choice"],
                "difficulty": difficulty,
            },
            target_count=count,
        )

        questions = await self._adapter.generate_questions(
            session_id=sid,
            user_id=user_id,
            chapter_ids=chapter_ids or [],
            question_types=question_types or ["choice"],
            difficulty=difficulty,
            count=count,
        )

        if len(questions) < 3:
            raise TrainingError(
                code="EVIDENCE_INSUFFICIENT",
                message=f"证据不足：仅生成 {len(questions)} 题（需要至少 3 题）。",
                retryable=False,
            )

        for q in questions:
            pub = q["public"]
            priv = q.get("private")
            await repo.insert_practice_item(
                self._session,
                session_id=sid,
                user_id=user_id,
                order_no=pub["order_no"],
                question_type=pub["question_type"],
                stem=pub.get("stem", ""),
                options=pub.get("options"),
                source_kind=pub.get("source_kind", "generated"),
                source_label=pub.get("source_label", ""),
                question_version="1.0",
                public_snapshot=pub,
                private_snapshot=priv,
            )

        await self._session.commit()
        return {"session_id": sid, "thread_id": tid, "total_questions": len(questions)}

    # ---- Next Question ----

    async def get_next_question(
        self, *, session_id: str, user_id: str,
    ) -> NextQuestionResponse | None:
        """获取当前未完成的下一题。

        幂等：同一 session 重复调用返回当前题，不创建重复题。
        """
        ps = await repo.get_practice_session(
            self._session, session_id, user_id=user_id,
        )
        if ps is None:
            raise TrainingError(
                code="RESOURCE_NOT_FOUND",
                message="训练会话不存在。",
                retryable=False,
            )

        items = await repo.list_items_for_session(
            self._session, session_id, user_id=user_id,
        )
        if not items:
            return None

        total = len(items)
        # 找到第一个未完成的题（通过检查 answer_submissions）
        from sqlalchemy import select

        from apps.api.db.models.answer_submission import AnswerSubmission

        for item in items:
            result = await self._session.execute(
                select(AnswerSubmission).where(
                    AnswerSubmission.item_id == item.id,
                ),
            )
            submitted = result.scalar_one_or_none()
            if submitted is None:
                # 第一道未提交的题
                current = item.order_no
                return NextQuestionResponse(
                    item_id=str(item.id),
                    order_no=item.order_no,
                    question_type=item.question_type,
                    difficulty=item.public_snapshot.get("difficulty", 2),
                    stem=item.stem,
                    options=item.options,
                    source_kind=item.source_kind,
                    source_label=item.source_label or "",
                    question_version=item.question_version,
                    progress={"current": current, "total": total},
                )

        # 全部完成
        return None

    # ---- Progress ----

    async def get_session_progress(
        self, *, session_id: str, user_id: str,
    ) -> dict:
        ps = await repo.get_practice_session(
            self._session, session_id, user_id=user_id,
        )
        if ps is None:
            raise TrainingError(
                code="RESOURCE_NOT_FOUND",
                message="训练会话不存在。",
                retryable=False,
            )
        items = await repo.list_items_for_session(
            self._session, session_id, user_id=user_id,
        )
        from sqlalchemy import select

        from apps.api.db.models.answer_submission import AnswerSubmission

        completed = 0
        for item in items:
            result = await self._session.execute(
                select(AnswerSubmission).where(
                    AnswerSubmission.item_id == item.id,
                ),
            )
            if result.scalar_one_or_none() is not None:
                completed += 1

        return {
            "session_id": session_id,
            "status": ps.status,
            "total_questions": len(items),
            "current_question": completed + 1 if completed < len(items) else len(items),
            "completed_questions": completed,
        }


# ---- Error ----

class TrainingError(Exception):
    def __init__(self, *, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# ---- Default adapter ----

_default = None


def _default_adapter():
    global _default
    if _default is None:
        from apps.api.services.training_adapter import FakeTrainingAdapter
        _default = FakeTrainingAdapter()
    return _default
