"""ChatService — 会话、消息和 Agent Run 状态转换的应用层服务。

所有查询方法强制要求 user_id，确保属主隔离。
状态转换调用运行状态机进行校验。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.chat_message import ChatMessage
from apps.api.db.models.chat_session import ChatSession
from apps.api.repositories import chat as chat_repo


class ChatService:
    """会话与消息持久化服务。

    所有读/写操作均强制属主隔离 —— user_id 为必填参数，
    直接传递至 Repository 层，作为 SQL WHERE 条件的一部分。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- Session ----

    async def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        thread_id: str,
        title: str | None = None,
    ) -> ChatSession:
        """创建新会话。"""
        return await chat_repo.create_chat_session(
            self._session,
            session_id=session_id,
            user_id=user_id,
            thread_id=thread_id,
            title=title,
        )

    async def get_session(
        self, *, session_id: str, user_id: str,
    ) -> ChatSession | None:
        """按 ID 获取会话（属主隔离）。"""
        return await chat_repo.get_chat_session(
            self._session, session_id, user_id=user_id,
        )

    async def list_sessions(
        self, *, user_id: str, limit: int = 50, offset: int = 0,
    ) -> list[ChatSession]:
        """列出用户的所有会话（最新在前）。"""
        return await chat_repo.list_chat_sessions(
            self._session, user_id, limit=limit, offset=offset,
        )

    async def update_session(
        self, *, session_id: str, user_id: str, **kwargs,
    ) -> None:
        """更新会话字段（属主隔离）。"""
        await chat_repo.update_chat_session(
            self._session, session_id, user_id=user_id, **kwargs,
        )

    # ---- Message ----

    async def insert_message(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
    ) -> ChatMessage:
        """插入消息（自动分配序号）。"""
        return await chat_repo.insert_message(
            self._session,
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            run_id=run_id,
        )

    async def get_messages(
        self,
        *,
        session_id: str,
        user_id: str,
        since_seq: int = -1,
    ) -> list[ChatMessage]:
        """获取会话消息列表（属主隔离）。"""
        return await chat_repo.get_messages(
            self._session, session_id, user_id=user_id, since_seq=since_seq,
        )

    async def get_assistant_message(
        self, *, run_id: str, user_id: str,
    ) -> ChatMessage | None:
        """按 run_id 获取助手消息（属主隔离，幂等检查）。"""
        return await chat_repo.get_assistant_message(
            self._session, run_id, user_id=user_id,
        )

    # ---- Run transition ----

    async def transition_run(
        self,
        *,
        run_id: str,
        user_id: str,
        target_status: str,
        **kwargs,
    ) -> None:
        """转换 AgentRun 状态（属主隔离 + 状态机校验）。"""
        await chat_repo.transition_run_status(
            self._session,
            run_id,
            target_status,
            user_id=user_id,
            **kwargs,
        )
