"""ORM models. Importing this package registers all models on Base.metadata.

Schema is owned by Alembic (raw-SQL baseline); these mirror the tables for queries.
"""

from app.models.audit import AuditEvent
from app.models.base import Base
from app.models.company import Company, Project
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseDirectFile,
    KnowledgeBaseMode,
    KBTextFile,
    KBVersion,
    KBVersionStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeStatus,
)
from app.models.lead import FollowupStatus, Lead, LeadEvent, LeadScore, LeadStage, FollowUpTask
from app.models.job import Job, JobStatus
from app.models.integration import IntegrationSetting
from app.models.persona import AdapterPersonaAssignment, Persona, PersonaVersion
from app.models.installation import (
    InstallationLifecycle,
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationState,
)
from app.models.contact import Contact, ContactChannelIdentity
from app.models.channel_account import ChannelAccount, ChannelAccountProject
from app.models.case_workflow import (
    CaseTagDefinition,
    CaseWorkflowStage,
    CaseWorkflowTransition,
    CaseWorkflowVersion,
)
from app.models.case import (
    Case,
    CaseFollowup,
    CaseLifecycle,
    CaseNote,
    CaseTagAssignment,
    FollowupStatus as CaseFollowupStatus,
)
from app.models.external_source_sync_state import ExternalSourceSyncState
from app.models.single_page_external_source_sync_state import SinglePageExternalSourceSyncState
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
from app.models.outbox import OutboxStatus, OutboundOutbox
from app.models.provenance import (
    DocumentStatus,
    ExtractionRun,
    ExtractionRunStatus,
    FaqEntry,
    FaqResolutionType,
    FieldEvidence,
    JobBenefit,
    JobLocation,
    JobRequirement,
    JobShift,
    KnowledgeScope,
    PublishedStatus,
    SourceDocument,
    SourceFragment,
    WorkingHours,
    WorkingHoursException,
)
from app.models.ingestion_template import (
    IngestionTemplate,
    IngestionTemplateAssignment,
    IngestionTemplateVersion,
    IngestionRunStatus,
    KBIngestionFileRun,
    KBIngestionRun,
    StructuredFact,
    TemplateVersionStatus,
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
    "KnowledgeBase",
    "KnowledgeBaseDirectFile",
    "KnowledgeBaseMode",
    "KnowledgeDocument",
    "KnowledgeStatus",
    "KBVersion",
    "KBVersionStatus",
    "KBTextFile",
    "FollowupStatus",
    "Lead",
    "LeadEvent",
    "LeadScore",
    "LeadStage",
    "FollowUpTask",
    "Job",
    "JobStatus",
    "IntegrationSetting",
    "Persona",
    "PersonaVersion",
    "AdapterPersonaAssignment",
    "InstallationLifecycle",
    "InstallationManifestRevision",
    "InstallationManifestValidation",
    "InstallationState",
    "Contact",
    "ContactChannelIdentity",
    "ChannelAccount",
    "ChannelAccountProject",
    "CaseWorkflowVersion",
    "CaseWorkflowStage",
    "CaseWorkflowTransition",
    "CaseTagDefinition",
    "Case",
    "CaseLifecycle",
    "CaseTagAssignment",
    "CaseNote",
    "CaseFollowup",
    "CaseFollowupStatus",
    "PasswordResetOtp",
    "ExternalSourceSyncState",
    "SinglePageExternalSourceSyncState",
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
    "OutboundOutbox",
    "OutboxStatus",
    "SourceDocument",
    "SourceFragment",
    "ExtractionRun",
    "FieldEvidence",
    "DocumentStatus",
    "ExtractionRunStatus",
    "FaqEntry",
    "FaqResolutionType",
    "JobBenefit",
    "JobLocation",
    "JobRequirement",
    "JobShift",
    "KnowledgeScope",
    "PublishedStatus",
    "WorkingHours",
    "WorkingHoursException",
    "IngestionTemplate",
    "IngestionTemplateVersion",
    "IngestionTemplateAssignment",
    "KBIngestionRun",
    "KBIngestionFileRun",
    "StructuredFact",
    "TemplateVersionStatus",
    "IngestionRunStatus",
]
