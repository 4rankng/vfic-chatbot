"""Immutable installation revisions, validations, and singleton lifecycle state."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InstallationLifecycle(str, enum.Enum):
    unconfigured = "UNCONFIGURED"
    draft = "DRAFT"
    validated = "VALIDATED"
    active = "ACTIVE"
    suspended = "SUSPENDED"
    upgrade_required = "UPGRADE_REQUIRED"


class InstallationManifestRevision(Base):
    __tablename__ = "installation_manifest_revisions"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(customer_identity) = 'object'",
            name="installation_customer_identity_object",
        ),
        CheckConstraint("jsonb_typeof(branding) = 'object'", name="installation_branding_object"),
        CheckConstraint(
            "jsonb_typeof(terminology) = 'object'", name="installation_terminology_object"
        ),
        CheckConstraint(
            "jsonb_typeof(workflow_policy) = 'object'", name="installation_workflow_policy_object"
        ),
        CheckConstraint(
            "jsonb_typeof(capability_ids) = 'array'", name="installation_capability_ids_array"
        ),
        CheckConstraint(
            "jsonb_typeof(template_version_refs) = 'array'", name="installation_template_refs_array"
        ),
        CheckConstraint(
            "jsonb_typeof(provider_policy) = 'object'", name="installation_provider_policy_object"
        ),
        CheckConstraint(
            "jsonb_typeof(integration_requirements) = 'array'",
            name="installation_integration_requirements_array",
        ),
        CheckConstraint(
            "authentication_policy IS NULL OR jsonb_typeof(authentication_policy) = 'object'",
            name="installation_authentication_policy_object",
        ),
        CheckConstraint(
            "(authentication_policy IS NULL) = (authentication_policy_checksum IS NULL)",
            name="installation_authentication_policy_pair",
        ),
        CheckConstraint(
            "authentication_policy_checksum IS NULL OR "
            "authentication_policy_checksum ~ '^[0-9a-f]{64}$'",
            name="installation_authentication_policy_checksum_sha256",
        ),
        CheckConstraint(
            "pack_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND manifest_checksum ~ '^[0-9a-f]{64}$' "
            "AND workflow_policy_checksum ~ '^[0-9a-f]{64}$' "
            "AND provider_policy_checksum ~ '^[0-9a-f]{64}$'",
            name="installation_revision_checksums_sha256",
        ),
        CheckConstraint(
            "pack_key ~ '^[a-z0-9][a-z0-9._-]*$'",
            name="installation_revision_pack_key_canonical",
        ),
        CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="installation_revision_currency_uppercase",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    revision_no: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    predecessor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT")
    )
    pack_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pack_version: Mapped[str] = mapped_column(String(32), nullable=False)
    pack_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_identity: Mapped[dict] = mapped_column(JSONB, nullable=False)
    branding: Mapped[dict] = mapped_column(JSONB, nullable=False)
    locale: Mapped[str] = mapped_column(String(35), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    terminology: Mapped[dict] = mapped_column(JSONB, nullable=False)
    workflow_policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    workflow_policy_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    persona_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persona_versions.id", ondelete="RESTRICT"), nullable=False
    )
    template_version_refs: Mapped[list] = mapped_column(JSONB, nullable=False)
    provider_policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provider_policy_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    integration_requirements: Mapped[list] = mapped_column(JSONB, nullable=False)
    authentication_policy: Mapped[dict | None] = mapped_column(JSONB)
    authentication_policy_checksum: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class InstallationManifestValidation(Base):
    __tablename__ = "installation_manifest_validations"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(issues) = 'array'", name="installation_validation_issues_array"
        ),
        CheckConstraint(
            "jsonb_typeof(reference_snapshot) = 'object'",
            name="installation_validation_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(template_checksums) = 'object'",
            name="installation_validation_templates_object",
        ),
        CheckConstraint(
            "jsonb_typeof(active_kb_vector) = 'array'",
            name="installation_validation_kb_vector_array",
        ),
        CheckConstraint(
            "manifest_checksum ~ '^[0-9a-f]{64}$' "
            "AND pack_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND persona_checksum ~ '^[0-9a-f]{64}$' "
            "AND workflow_policy_checksum ~ '^[0-9a-f]{64}$' "
            "AND provider_policy_checksum ~ '^[0-9a-f]{64}$'",
            name="installation_validation_checksums_sha256",
        ),
        CheckConstraint(
            "authentication_policy_checksum IS NULL OR "
            "authentication_policy_checksum ~ '^[0-9a-f]{64}$'",
            name="installation_validation_authentication_checksum_sha256",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    validator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_valid: Mapped[bool] = mapped_column(nullable=False)
    issues: Mapped[list] = mapped_column(JSONB, nullable=False)
    reference_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    pack_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_policy_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_policy_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    authentication_policy_checksum: Mapped[str | None] = mapped_column(String(64))
    template_checksums: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active_kb_vector: Mapped[list] = mapped_column(JSONB, nullable=False)
    validated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class InstallationState(Base):
    __tablename__ = "installation_state"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="installation_state_singleton"),
        CheckConstraint(
            "lifecycle IN ('DRAFT','VALIDATED','ACTIVE','SUSPENDED')",
            name="installation_state_lifecycle",
        ),
        CheckConstraint("authority_generation >= 0", name="installation_state_generation"),
        CheckConstraint("lock_version >= 0", name="installation_state_lock_version"),
        CheckConstraint(
            "lifecycle NOT IN ('ACTIVE','SUSPENDED') OR "
            "(active_revision_id IS NOT NULL AND active_validation_id IS NOT NULL)",
            name="installation_state_active_pointers",
        ),
        CheckConstraint(
            "lifecycle <> 'VALIDATED' OR validated_revision_id IS NOT NULL",
            name="installation_state_validated_pointer",
        ),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    current_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    validated_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT")
    )
    active_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT")
    )
    active_validation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("installation_manifest_validations.id", ondelete="RESTRICT")
    )
    previous_active_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("installation_manifest_revisions.id", ondelete="RESTRICT")
    )
    authority_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lock_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class InstallationSetupDraft(Base):
    """Mutable singleton authoring workspace; never runtime authority."""

    __tablename__ = "installation_setup_drafts"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="installation_setup_draft_singleton"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="installation_setup_draft_payload_object"
        ),
        CheckConstraint("lock_version >= 0", name="installation_setup_draft_lock_version"),
    )

    singleton_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    lock_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
