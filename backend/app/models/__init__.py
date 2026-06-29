"""ORM models. Importing this package registers all models on Base.metadata.

Schema is owned by Alembic (raw-SQL baseline); these mirror the tables for queries.
"""
from app.models.audit import AuditEvent
from app.models.base import Base
from app.models.company import Company, Project
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeStatus
from app.models.lead import FollowupStatus, Lead, LeadEvent, LeadScore, LeadStage, FollowUpTask
from app.models.job import Job, JobStatus
from app.models.persona import Persona
from app.models.password_reset import PasswordResetOtp
from app.models.worker_feature import JobFeatureValue, WorkerFeatureCatalog
from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.user import Role, User

__all__ = [
    "Base",
    "User",
    "Role",
    "AuditEvent",
    "Company",
    "Project",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeStatus",
    "FollowupStatus",
    "Lead",
    "LeadEvent",
    "LeadScore",
    "LeadStage",
    "FollowUpTask",
    "Job",
    "JobStatus",
    "Persona",
    "PasswordResetOtp",
    "WorkerFeatureCatalog",
    "JobFeatureValue",
    "Conversation",
    "ConversationMode",
    "ConversationStatus",
    "Message",
    "MessageSender",
    "DeliveryStatus",
    "BotRun",
    "BotRunOutcome",
]
