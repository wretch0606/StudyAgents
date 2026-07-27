"""全部 ORM 模型 — Alembic autogenerate 通过导入此模块收集 metadata。"""

from apps.api.db.models.agent_event import AgentEvent
from apps.api.db.models.agent_run import AgentRun
from apps.api.db.models.auth_session import AuthSession
from apps.api.db.models.chat_message import ChatMessage
from apps.api.db.models.chat_session import ChatSession
from apps.api.db.models.document import Document
from apps.api.db.models.idempotency import IdempotencyRecord
from apps.api.db.models.ingestion_job import IngestionJob
from apps.api.db.models.user import User

__all__ = [
    "AgentEvent",
    "AgentRun",
    "AuthSession",
    "ChatMessage",
    "ChatSession",
    "Document",
    "IdempotencyRecord",
    "IngestionJob",
    "User",
]
