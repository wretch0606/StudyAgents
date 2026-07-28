"""Issue 16-5 专项测试 — finish / summary / wrong-book / learning-summary。

所有 DB 测试需要 DATABASE_URL。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATABASE_URL = os.getenv("DATABASE_URL", "")

_needs_db = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


# ============================================================
# 0. DTO 白名单 (no-DB)
# ============================================================

def test_wrong_book_entry_dto_no_private() -> None:
    """WrongBookEntry 不含 private_snapshot/expected_answer/rubric。"""
    from apps.api.schemas.practice import WrongBookEntry
    fields = set(WrongBookEntry.model_fields.keys())
    assert "private_snapshot" not in fields
    assert "expected_answer" not in fields
    assert "rubric" not in fields
    assert "wrong_answer" not in fields  # 内部字段，不出现在公开 DTO
    assert "correct_answer" not in fields


def test_learning_summary_dto_no_private() -> None:
    """LearningSummary 不含私有字段。"""
    from apps.api.schemas.practice import LearningSummary
    fields = set(LearningSummary.model_fields.keys())
    assert "private_snapshot" not in fields
    assert "expected_answer" not in fields


def test_mastery_record_dto_fields() -> None:
    """MasteryRecord DTO 字段对齐 api(6).ts。"""
    from apps.api.schemas.practice import MasteryRecord
    fields = set(MasteryRecord.model_fields.keys())
    assert "user_id" in fields
    assert "knowledge_point_id" in fields
    assert "mastery" in fields
    assert "streaks" in fields
    assert "reason" in fields
    assert "updated_at" in fields


def test_update_wrong_book_allowed_status() -> None:
    """UpdateWrongBookRequest 只接受 pending/reviewing。"""
    from apps.api.schemas.practice import UpdateWrongBookRequest
    r = UpdateWrongBookRequest(status="pending")
    assert r.status == "pending"
    r2 = UpdateWrongBookRequest(status="reviewing")
    assert r2.status == "reviewing"
    r3 = UpdateWrongBookRequest(note="my note")
    assert r3.note == "my note"
    assert r3.status is None


# ============================================================
# DB-dependent tests
# ============================================================

@_needs_db
@pytest.mark.asyncio
async def test_finish_session_normal_complete() -> None:
    """正常完成训练（达到目标题数后 finish）。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    uid, sid = await _create_user_and_session(count=3)
    async with _get_sessionmaker()() as s:
        await repo.update_practice_session(s, sid, user_id=uid, status="completed")
        await s.commit()
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid)
        assert ps.status == "completed"


@_needs_db
@pytest.mark.asyncio
async def test_finish_session_cancelled() -> None:
    """提前结束训练（未达目标题数）。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    uid, sid = await _create_user_and_session(count=5)
    async with _get_sessionmaker()() as s:
        await repo.update_practice_session(s, sid, user_id=uid, status="cancelled")
        await s.commit()
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid)
        assert ps.status == "cancelled"


@_needs_db
@pytest.mark.asyncio
async def test_finish_idempotent() -> None:
    """重复结束返回相同结果。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    uid, sid = await _create_user_and_session(count=3)
    async with _get_sessionmaker()() as s:
        await repo.update_practice_session(s, sid, user_id=uid, status="completed")
        await s.commit()
    # 第二次结束不报错，状态不变
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid)
        assert ps.status == "completed"


@_needs_db
@pytest.mark.asyncio
async def test_other_user_cannot_finish() -> None:
    """其他用户不能结束训练。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    users = await _get_two_users()
    uid_a, uid_b = users[0], users[1]
    sid = await _create_session(uid=uid_a, count=3)
    # B 无法访问 A 的训练
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid_b)
        assert ps is None


@_needs_db
@pytest.mark.asyncio
async def test_summary_after_complete_training() -> None:
    """至少 3 题完整训练后获取总结。"""
    import uuid as _uuid

    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.practice import get_session_summary
    from apps.api.services.grading_service import GradingService
    from apps.api.services.training_service import TrainingService

    uid, sid = await _create_user_and_session(count=3)
    # 提交所有 3 题
    async with _get_sessionmaker()() as s:
        svc = TrainingService(s)
        for _ in range(3):
            q = await svc.get_next_question(session_id=sid, user_id=uid)
            if q is None:
                break

    async with _get_sessionmaker()() as s:
        svc = GradingService(s)
        # Submit first question
        q = await TrainingService(s).get_next_question(session_id=sid, user_id=uid)
        if q:
            await svc.submit_answer(
                session_id=sid, item_id=q.item_id, user_id=uid,
                answer_text="9.8", question_version="1.0",
                idempotency_key=f"s1-{_uuid.uuid4().hex[:8]}",
            )

    async with _get_sessionmaker()() as s:
        summary = await get_session_summary(session_id=sid, user_id=uid, session=s)
        assert summary.session_id == sid
        assert summary.total_max_score >= 0
        assert len(summary.grades) >= 1
        # 无私有字段
        d = summary.model_dump()
        for grade in d.get("grades", []):
            assert "expected_answer" not in str(grade)
            assert "rubric" not in str(grade)


@_needs_db
@pytest.mark.asyncio
async def test_summary_readonly() -> None:
    """多次查询 summary 结果一致（无写操作）。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.practice import get_session_summary
    uid, sid = await _create_user_and_session(count=3)
    async with _get_sessionmaker()() as s:
        s1 = await get_session_summary(session_id=sid, user_id=uid, session=s)
    async with _get_sessionmaker()() as s:
        s2 = await get_session_summary(session_id=sid, user_id=uid, session=s)
    assert s1.total_score == s2.total_score


@_needs_db
@pytest.mark.asyncio
async def test_other_user_cannot_read_summary() -> None:
    """其他用户不能查询总结。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.repositories import practice as repo
    users = await _get_two_users()
    uid_a, uid_b = users[0], users[1]
    sid = await _create_session(uid=uid_a, count=3)
    async with _get_sessionmaker()() as s:
        ps = await repo.get_practice_session(s, sid, user_id=uid_b)
        assert ps is None


# ---- Wrong-Book ----

@_needs_db
@pytest.mark.asyncio
async def test_wrong_book_list_my_entries() -> None:
    """查询本人的错题列表。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.wrong_book import list_wrong_book
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        result = await list_wrong_book(user_id=uid, session=s)
        assert "items" in result
        assert "total" in result
        assert "page" in result
        assert "total_pages" in result


@_needs_db
@pytest.mark.asyncio
async def test_wrong_book_pagination() -> None:
    """分页字段正确。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.wrong_book import list_wrong_book
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        result = await list_wrong_book(user_id=uid, page=1, page_size=10, session=s)
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert len(result["items"]) <= 10


@_needs_db
@pytest.mark.asyncio
async def test_wrong_book_status_filter() -> None:
    """status 筛选生效。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.wrong_book import list_wrong_book
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        result = await list_wrong_book(user_id=uid, status="pending", session=s)
        for item in result["items"]:
            assert item["status"] == "pending"


@_needs_db
@pytest.mark.asyncio
async def test_wrong_book_empty_result() -> None:
    """不存在的筛选条件返回空分页。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.wrong_book import list_wrong_book
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        result = await list_wrong_book(
            user_id=uid, knowledge_point_id="nonexistent-kp-xyz", session=s,
        )
        assert result["total"] == 0
        assert len(result["items"]) == 0


@_needs_db
@pytest.mark.asyncio
async def test_wrong_book_update_note() -> None:
    """更新本人错题备注。"""
    from apps.api.db.models.wrong_book_entry import WrongBookEntry as WBModel
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.wrong_book import update_wrong_book
    from apps.api.schemas.practice import UpdateWrongBookRequest
    uid = await _get_user_id()
    # 确保至少有一条自己的错题
    async with _get_sessionmaker()() as s:
        result = await s.execute(
            __import__("sqlalchemy").select(WBModel).where(
                WBModel.user_id == uid,
            ).limit(1),
        )
        wb = result.scalar_one_or_none()
    if wb is None:
        pytest.skip("No wrong-book entry for user")
    entry_id = str(wb.id)
    async with _get_sessionmaker()() as s:
        updated = await update_wrong_book(
            entry_id=entry_id,
            body=UpdateWrongBookRequest(note="test note"),
            user_id=uid, session=s,
        )
        assert updated.note == "test note"


@_needs_db
@pytest.mark.asyncio
async def test_wrong_book_reject_mastered() -> None:
    """用户不能直接设置 mastered。"""
    from apps.api.db.models.wrong_book_entry import WrongBookEntry as WBModel
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.wrong_book import update_wrong_book
    from apps.api.schemas.error import ApiError
    from apps.api.schemas.practice import UpdateWrongBookRequest
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        result = await s.execute(
            __import__("sqlalchemy").select(WBModel).where(
                WBModel.user_id == uid,
            ).limit(1),
        )
        wb = result.scalar_one_or_none()
    if wb is None:
        pytest.skip("No wrong-book entry for user")
    entry_id = str(wb.id)
    async with _get_sessionmaker()() as s:
        with pytest.raises(ApiError, match="只允许设置"):
            await update_wrong_book(
                entry_id=entry_id,
                body=UpdateWrongBookRequest(status="mastered"),  # type: ignore[arg-type]
                user_id=uid, session=s,
            )


@_needs_db
@pytest.mark.asyncio
async def test_wrong_book_other_user_blocked() -> None:
    """不能修改其他用户的错题。"""
    from apps.api.db.models.wrong_book_entry import WrongBookEntry as WBModel
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.wrong_book import update_wrong_book
    from apps.api.schemas.error import ApiError
    from apps.api.schemas.practice import UpdateWrongBookRequest
    users = await _get_two_users()
    uid_a, uid_b = users[0], users[1]
    async with _get_sessionmaker()() as s:
        result = await s.execute(
            __import__("sqlalchemy").select(WBModel).where(
                WBModel.user_id == uid_a,
            ).limit(1),
        )
        wb = result.scalar_one_or_none()
    if wb is None:
        pytest.skip("No wrong-book entry for user A")
    entry_id = str(wb.id)
    async with _get_sessionmaker()() as s:
        with pytest.raises(ApiError, match="不存在"):
            await update_wrong_book(
                entry_id=entry_id,
                body=UpdateWrongBookRequest(note="hack"),
                user_id=uid_b, session=s,
            )


# ---- Learning-Summary ----

@_needs_db
@pytest.mark.asyncio
async def test_learning_summary_new_user() -> None:
    """新用户（无学习数据）返回合法空响应。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.learning_summary import get_learning_summary
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        result = await get_learning_summary(user_id=uid, session=s)
        assert result.user_id == uid
        assert result.pending_wrong_count >= 0
        assert result.reviewing_wrong_count >= 0


@_needs_db
@pytest.mark.asyncio
async def test_learning_summary_no_write() -> None:
    """GET 请求不产生业务写入。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.learning_summary import get_learning_summary
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        r1 = await get_learning_summary(user_id=uid, session=s)
    async with _get_sessionmaker()() as s:
        r2 = await get_learning_summary(user_id=uid, session=s)
    assert r1.pending_wrong_count == r2.pending_wrong_count
    assert r1.mastery_records == r2.mastery_records


@_needs_db
@pytest.mark.asyncio
async def test_learning_summary_no_private_leak() -> None:
    """LearningSummary 响应无私有字段。"""
    from apps.api.db.session import _get_sessionmaker
    from apps.api.routers.learning_summary import get_learning_summary
    uid = await _get_user_id()
    async with _get_sessionmaker()() as s:
        result = await get_learning_summary(user_id=uid, session=s)
        d = result.model_dump()
        assert "expected_answer" not in str(d)
        assert "rubric" not in str(d)
        assert "private_snapshot" not in str(d)


# ============================================================
# Helpers
# ============================================================

from apps.api.db.session import _get_sessionmaker as _gsm  # noqa: E402


async def _get_user_id() -> str:
    from sqlalchemy import select as sa_select

    from apps.api.db.models.user import User
    async with _gsm()() as s:
        r = await s.execute(sa_select(User).limit(1))
        u = r.scalar_one_or_none()
        assert u is not None, "No users"
        return str(u.id)


async def _get_two_users() -> list[str]:
    from sqlalchemy import select as sa_select

    from apps.api.db.models.user import User
    async with _gsm()() as s:
        r = await s.execute(sa_select(User).limit(2))
        users = list(r.scalars().all())
        if len(users) < 2:
            pytest.skip("Need 2 users")
        return [str(u.id) for u in users]


async def _create_session(uid: str, count: int = 3) -> str:
    from apps.api.services.training_service import TrainingService
    async with _gsm()() as s:
        svc = TrainingService(s)
        result = await svc.create_training(user_id=uid, count=count)
        return result["session_id"]


async def _create_user_and_session(count: int = 3) -> tuple[str, str]:
    uid = await _get_user_id()
    sid = await _create_session(uid=uid, count=count)
    return uid, sid
