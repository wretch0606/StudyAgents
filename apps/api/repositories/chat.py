"""Chat persistence repositories — ChatSession and ChatMessage CRUD."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.chat_message import ChatMessage as ChatMessageModel
from apps.api.db.models.chat_session import ChatSession as ChatSessionModel
from apps.api.db.models.run_state import validate_transition

# ---- ChatSession ----

async def create_chat_session(
    session: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    thread_id: str,
    title: str | None = None,
) -> ChatSessionModel:
    """Create a new chat session."""
    chat = ChatSessionModel(
        id=session_id, user_id=user_id, thread_id=thread_id, title=title,
    )
    session.add(chat)
    await session.flush()
    return chat


async def get_chat_session(
    session: AsyncSession, session_id: str, *, user_id: str,
) -> ChatSessionModel | None:
    """Get a chat session, scoped to user_id for mandatory ownership isolation."""
    result = await session.execute(
        select(ChatSessionModel).where(
            ChatSessionModel.id == session_id,
            ChatSessionModel.user_id == user_id,
        ),
    )
    return result.scalar_one_or_none()


async def list_chat_sessions(
    session: AsyncSession,
    user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[ChatSessionModel]:
    """List chat sessions for a user, newest first."""
    result = await session.execute(
        select(ChatSessionModel)
        .where(ChatSessionModel.user_id == user_id)
        .order_by(ChatSessionModel.updated_at.desc())
        .limit(limit)
        .offset(offset),
    )
    return list(result.scalars().all())


async def update_chat_session(
    session: AsyncSession, session_id: str, *, user_id: str, **kwargs,
) -> None:
    """Update chat session fields (e.g. title). Owner isolation enforced."""
    chat = await get_chat_session(session, session_id, user_id=user_id)
    if chat is None:
        return
    for key, value in kwargs.items():
        if hasattr(chat, key):
            setattr(chat, key, value)
    await session.flush()


# ---- ChatMessage ----

async def get_next_message_sequence(
    session: AsyncSession, session_id: str,
) -> int:
    """Get the next sequence_no for messages in a session."""
    result = await session.execute(
        select(ChatMessageModel.sequence_no)
        .where(ChatMessageModel.session_id == session_id)
        .order_by(ChatMessageModel.sequence_no.desc())
        .limit(1),
    )
    last = result.scalar_one_or_none()
    return (last + 1) if last is not None else 0


async def insert_message(
    session: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    role: str,
    content: str,
    run_id: str | None = None,
    sequence_no: int | None = None,
) -> ChatMessageModel:
    """Insert a message. Auto-computes sequence_no if not provided."""
    if sequence_no is None:
        sequence_no = await get_next_message_sequence(session, session_id)
    msg = ChatMessageModel(
        session_id=session_id,
        user_id=user_id,
        role=role,
        content=content,
        run_id=run_id,
        sequence_no=sequence_no,
    )
    session.add(msg)
    await session.flush()
    return msg


async def get_messages(
    session: AsyncSession,
    session_id: str,
    *,
    user_id: str,
    since_seq: int = -1,
) -> list[ChatMessageModel]:
    """Get messages in a session, scoped to user_id for mandatory ownership isolation."""
    stmt = select(ChatMessageModel).where(
        ChatMessageModel.session_id == session_id,
        ChatMessageModel.user_id == user_id,
    )
    if since_seq >= 0:
        stmt = stmt.where(ChatMessageModel.sequence_no > since_seq)
    stmt = stmt.order_by(ChatMessageModel.sequence_no)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_assistant_message(
    session: AsyncSession, run_id: str, *, user_id: str,
) -> ChatMessageModel | None:
    """Get the assistant message for a given run (idempotency check, owner-isolated)."""
    result = await session.execute(
        select(ChatMessageModel).where(
            ChatMessageModel.run_id == run_id,
            ChatMessageModel.role == "assistant",
            ChatMessageModel.user_id == user_id,
        ),
    )
    return result.scalar_one_or_none()


# ---- Run state transition (wraps existing agent_run repo) ----

async def transition_run_status(
    session: AsyncSession,
    run_id: str,
    target_status: str,
    *,
    user_id: str,
    **kwargs,
) -> None:
    """Transition an AgentRun to a new status, validating the state machine.

    Requires current status from DB to validate before updating.
    Owner isolation enforced via mandatory user_id.
    """
    from apps.api.repositories.agent_run import get_run, update_run_status  # noqa: PLC0415

    run = await get_run(session, run_id, user_id=user_id)
    if run is None:
        raise ValueError(f"AgentRun not found: {run_id}")
    validate_transition(run.status, target_status)
    await update_run_status(session, run_id, target_status, user_id=user_id, **kwargs)
