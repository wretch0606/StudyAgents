"""全部 ORM 模型 — Alembic autogenerate 通过导入此模块收集 metadata。"""

from apps.api.db.models.agent_event import AgentEvent
from apps.api.db.models.agent_run import AgentRun
from apps.api.db.models.answer_submission import AnswerSubmission
from apps.api.db.models.auth_session import AuthSession
from apps.api.db.models.chat_message import ChatMessage
from apps.api.db.models.chat_session import ChatSession
from apps.api.db.models.document import Document
from apps.api.db.models.document_page import DocumentPage
from apps.api.db.models.grade_result import GradeResult
from apps.api.db.models.idempotency import IdempotencyRecord
from apps.api.db.models.ingestion_job import IngestionJob
from apps.api.db.models.knowledge_chunk import KnowledgeChunk
from apps.api.db.models.mastery_change_log import MasteryChangeLog
from apps.api.db.models.mastery_record import MasteryRecord
from apps.api.db.models.practice_item import PracticeItem
from apps.api.db.models.practice_session import PracticeSession
from apps.api.db.models.user import User
from apps.api.db.models.wrong_book_entry import WrongBookEntry

__all__ = [
    "AgentEvent",
    "AgentRun",
    "AnswerSubmission",
    "AuthSession",
    "ChatMessage",
    "ChatSession",
    "Document",
    "DocumentPage",
    "GradeResult",
    "IdempotencyRecord",
    "IngestionJob",
    "KnowledgeChunk",
    "MasteryChangeLog",
    "MasteryRecord",
    "PracticeItem",
    "PracticeSession",
    "User",
    "WrongBookEntry",
]
