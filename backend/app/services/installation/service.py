"""Fail-closed installation revision validation and lifecycle transitions."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.registry import CapabilityRegistry, get_capability_registry
from app.models.installation import (
    InstallationLifecycle,
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationState,
)
from app.models.case_workflow import CaseWorkflowVersion
from app.schemas.installation import (
    InstallationAdminOut,
    InstallationRevisionCreate,
    InstallationRevisionOut,
    InstallationRuntimeOut,
    InstallationValidationOut,
)
from app.services.audit_service import record_audit
from app.services.errors import InstallationError
from app.services.installation.authority import RuntimeAuthorityFingerprint, RuntimeAuthorityStamp
from app.services.installation.hashing import sha256_json
from app.services.installation.catalog import (
    CHANNEL_CAPABILITY_REQUIREMENTS,
    CHAT_INTEGRATION_REFERENCES,
    EMBEDDING_INTEGRATION_REFERENCES,
    integration_reference_ids,
)
from app.services.installation.repository import InstallationRepository
from app.services.installation.runtime import (
    cache_fingerprint,
    get_cached_fingerprint,
    invalidate_installation_cache,
)


VALIDATOR_VERSION = "1"
logger = logging.getLogger(__name__)
_SECRET_VALUE_PATTERN = re.compile(
    r"^(?:sk-|xox[a-z]*-|ghp_|github_pat_|AIza)|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
    re.IGNORECASE,
)
PUBLIC_CUSTOMER_IDENTITY_KEYS = {
    "display_name",
    "legal_name",
    "support_name",
    "support_email",
    "support_phone",
    "website_url",
    "address",
}
PUBLIC_BRANDING_KEYS = {
    "app_name",
    "primary_color",
    "secondary_color",
}


@dataclass(frozen=True, slots=True)
class ActiveInstallation:
    revision: InstallationManifestRevision
    fingerprint: RuntimeAuthorityFingerprint


class InstallationService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        self.db = db
        self.repo = InstallationRepository(db)
        self.registry = registry or get_capability_registry()

    async def create_revision(
        self,
        body: InstallationRevisionCreate,
        actor_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> InstallationManifestRevision:
        await self.repo.acquire_authority_lock()
        state = await self.repo.get_state(for_update=True)
        lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
        self._assert_expected_lock(state, body.expected_lock_version, lifecycle)
        try:
            pack = self.registry.get_pack(body.pack_key)
            capability_ids = self.registry.validate_selection(body.pack_key, body.capability_ids)
        except ValueError as exc:
            raise self._error(
                str(exc), "INSTALLATION_VALIDATION_FAILED", lifecycle, status_code=422
            ) from exc

        selection_issues: list[dict[str, str | None]] = []
        if body.workflow_policy.workflow_id not in pack.workflow_ids:
            selection_issues.append(self._issue("WORKFLOW_INVALID", "workflow_policy.workflow_id"))
        if body.workflow_policy.workflow_version_id is None:
            selection_issues.append(
                self._issue("WORKFLOW_VERSION_REQUIRED", "workflow_policy.workflow_version_id")
            )
        else:
            workflow_version = await self.db.get(
                CaseWorkflowVersion, body.workflow_policy.workflow_version_id
            )
            if (
                workflow_version is None
                or workflow_version.checksum != body.workflow_policy.workflow_version_checksum
                or workflow_version.pack_key != body.pack_key
                or workflow_version.workflow_key != body.workflow_policy.workflow_id
            ):
                selection_issues.append(
                    self._issue("WORKFLOW_VERSION_MISMATCH", "workflow_policy.workflow_version_id")
                )
        missing_terms = set(pack.terminology_keys) - set(body.terminology)
        unknown_terms = set(body.terminology) - set(pack.terminology_keys)
        if missing_terms:
            selection_issues.append(
                self._issue(
                    "TERMINOLOGY_REQUIRED",
                    "terminology",
                    f"Missing terminology keys: {sorted(missing_terms)}",
                )
            )
        if unknown_terms:
            selection_issues.append(self._issue("TERMINOLOGY_KEY_INVALID", "terminology"))
        if body.provider_policy.chat_integration_key not in CHAT_INTEGRATION_REFERENCES:
            selection_issues.append(
                self._issue("INTEGRATION_REFERENCE_INVALID", "provider_policy.chat_integration_key")
            )
        if body.provider_policy.embedding_integration_key not in EMBEDDING_INTEGRATION_REFERENCES:
            selection_issues.append(
                self._issue(
                    "INTEGRATION_REFERENCE_INVALID", "provider_policy.embedding_integration_key"
                )
            )
        integration_refs = {item.key for item in body.integration_requirements}
        if integration_refs - set(integration_reference_ids()):
            selection_issues.append(
                self._issue("INTEGRATION_REFERENCE_INVALID", "integration_requirements")
            )
        required_refs = {
            reference
            for capability, reference in CHANNEL_CAPABILITY_REQUIREMENTS.items()
            if capability in capability_ids
        }
        if required_refs - integration_refs:
            selection_issues.append(
                self._issue("INTEGRATION_REQUIRED_BY_CAPABILITY", "integration_requirements")
            )
        if selection_issues:
            raise self._error(
                "Installation settings are not valid for the selected pack",
                "INSTALLATION_VALIDATION_FAILED",
                lifecycle,
                status_code=422,
                issues=selection_issues,
            )

        if state and state.active_revision_id:
            active = await self._revision_or_error(state.active_revision_id, lifecycle)
            if active.pack_key != body.pack_key:
                raise self._error(
                    "Industry pack is locked after activation",
                    "INSTALLATION_PACK_LOCKED",
                    lifecycle,
                )
        incompatible_data = (await self.repo.operational_data_kinds()) - set(
            pack.compatible_operational_data
        )
        if incompatible_data:
            raise self._error(
                f"Industry pack is incompatible with existing data: {sorted(incompatible_data)}",
                "INSTALLATION_PACK_LOCKED",
                lifecycle,
            )

        persona_version = await self.repo.get_persona_version(body.persona_version_id)
        if persona_version is None:
            raise self._error(
                "Persona version does not exist",
                "INSTALLATION_VALIDATION_FAILED",
                lifecycle,
                status_code=422,
                issues=[self._issue("PERSONA_VERSION_NOT_FOUND", "persona_version_id")],
            )
        secret_paths = {
            "customer_identity": body.customer_identity,
            "branding": body.branding,
            "terminology": body.terminology,
            "workflow_policy": body.workflow_policy,
            "provider_policy": body.provider_policy,
            "authentication_policy": body.authentication_policy,
        }
        secret_path = next(
            (
                path
                for path, value in secret_paths.items()
                if self._contains_secret_key(value) or self._contains_secret_value(value)
            ),
            None,
        )
        if secret_path is not None:
            raise self._error(
                "Installation settings must reference encrypted integrations, not contain secrets",
                "INSTALLATION_VALIDATION_FAILED",
                lifecycle,
                status_code=422,
                issues=[self._issue("PLAINTEXT_SECRET_FORBIDDEN", secret_path)],
            )

        data = body.model_dump(mode="json", exclude_none=True, exclude={"expected_lock_version"})
        workflow_checksum = sha256_json(data["workflow_policy"])
        provider_checksum = sha256_json(data["provider_policy"])
        authentication_checksum = sha256_json(data["authentication_policy"])
        pack_hash = self.registry.pack_contract_hash(pack.key)
        manifest_payload = {
            **data,
            "capability_ids": list(capability_ids),
            "pack_version": pack.version,
            "pack_contract_hash": pack_hash,
            "workflow_policy_checksum": workflow_checksum,
            "provider_policy_checksum": provider_checksum,
            "authentication_policy_checksum": authentication_checksum,
        }
        revision = InstallationManifestRevision(
            predecessor_id=state.current_revision_id if state else None,
            pack_key=pack.key,
            pack_version=pack.version,
            pack_contract_hash=pack_hash,
            manifest_checksum=sha256_json(manifest_payload),
            customer_identity=data["customer_identity"],
            branding=data["branding"],
            locale=data["locale"],
            timezone=data["timezone"],
            currency=data["currency"],
            terminology=data["terminology"],
            workflow_policy=data["workflow_policy"],
            workflow_policy_checksum=workflow_checksum,
            capability_ids=list(capability_ids),
            persona_version_id=body.persona_version_id,
            template_version_refs=data["template_version_refs"],
            provider_policy=data["provider_policy"],
            provider_policy_checksum=provider_checksum,
            integration_requirements=data["integration_requirements"],
            authentication_policy=data["authentication_policy"],
            authentication_policy_checksum=authentication_checksum,
            workflow_version_id=body.workflow_policy.workflow_version_id,
            workflow_version_checksum=body.workflow_policy.workflow_version_checksum,
            created_by=actor_id,
        )
        self.db.add(revision)
        await self.db.flush()
        if state is None:
            state = InstallationState(
                singleton_id=1,
                lifecycle=InstallationLifecycle.draft.value,
                current_revision_id=revision.id,
                authority_generation=0,
                lock_version=1,
            )
            self.db.add(state)
        else:
            state.current_revision_id = revision.id
            state.validated_revision_id = None
            if state.active_revision_id is None:
                state.lifecycle = InstallationLifecycle.draft.value
            state.lock_version += 1
            state.updated_at = func.now()
        await record_audit(
            self.db,
            action="create_installation_revision",
            actor_id=actor_id,
            target_type="installation_revision",
            target_id=str(revision.id),
            payload={"pack_key": pack.key, "manifest_checksum": revision.manifest_checksum},
        )
        if commit:
            await self.db.commit()
            await self._invalidate_cache_safely()
            await self.db.refresh(revision)
        return revision

    async def validate_revision(
        self,
        revision_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        commit: bool = True,
    ) -> InstallationManifestValidation:
        await self.repo.acquire_authority_lock()
        state = await self.repo.get_state(for_update=True)
        lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
        revision = await self._revision_or_error(revision_id, lifecycle)
        issues: list[dict[str, str | None]] = []

        if revision.workflow_version_id is None:
            issues.append(self._issue("WORKFLOW_VERSION_REQUIRED", "workflow_version_id"))
        else:
            workflow_version = await self.db.get(CaseWorkflowVersion, revision.workflow_version_id)
            if (
                workflow_version is None
                or revision.workflow_version_checksum is None
                or workflow_version.checksum != revision.workflow_version_checksum
                or workflow_version.pack_key != revision.pack_key
                or workflow_version.workflow_key != revision.workflow_policy.get("workflow_id")
            ):
                issues.append(self._issue("WORKFLOW_VERSION_MISMATCH", "workflow_version_id"))

        try:
            pack = self.registry.get_pack(revision.pack_key)
            selected = self.registry.validate_selection(revision.pack_key, revision.capability_ids)
            if pack.version != revision.pack_version:
                issues.append(self._issue("PACK_VERSION_MISMATCH", "pack_version"))
            if self.registry.pack_contract_hash(pack.key) != revision.pack_contract_hash:
                issues.append(self._issue("PACK_CONTRACT_MISMATCH", "pack_contract_hash"))
            if list(selected) != sorted(revision.capability_ids):
                issues.append(self._issue("CAPABILITY_SELECTION_INVALID", "capability_ids"))
        except ValueError as exc:
            issues.append(self._issue("PACK_UNKNOWN", "pack_key", str(exc)))

        if (
            revision.authentication_policy is None
            or revision.authentication_policy_checksum is None
            or sha256_json(revision.authentication_policy)
            != revision.authentication_policy_checksum
        ):
            issues.append(
                self._issue(
                    "AUTHENTICATION_POLICY_REQUIRED",
                    "authentication_policy",
                    "An explicit current authentication policy is required",
                )
            )

        persona = await self.repo.get_persona_version(revision.persona_version_id)
        if persona is None:
            issues.append(self._issue("PERSONA_VERSION_NOT_FOUND", "persona_version_id"))
            persona_checksum = ""
        else:
            persona_checksum = persona.checksum
            expected_persona_checksum = sha256_json(
                {"body_md": persona.body_md, "followup_rules": persona.followup_rules}
            )
            if persona.checksum != expected_persona_checksum:
                issues.append(self._issue("PERSONA_CHECKSUM_MISMATCH", "persona_version_id"))

        expected_refs = {
            str(item["version_id"]): str(item["checksum"])
            for item in revision.template_version_refs
        }
        actual_refs = await self.repo.template_checksums(
            [uuid.UUID(version_id) for version_id in expected_refs]
        )
        template_checksums: dict[str, str] = {}
        for version_id, expected_checksum in expected_refs.items():
            actual_checksum = actual_refs.get(version_id)
            if actual_checksum is None:
                issues.append(self._issue("TEMPLATE_VERSION_NOT_FOUND", "template_version_refs"))
            elif actual_checksum != expected_checksum:
                issues.append(self._issue("TEMPLATE_CHECKSUM_MISMATCH", "template_version_refs"))
            else:
                template_checksums[version_id] = actual_checksum

        required_keys = [str(item["key"]) for item in revision.integration_requirements]
        required_keys.extend(
            [
                str(revision.provider_policy["chat_integration_key"]),
                str(revision.provider_policy["embedding_integration_key"]),
            ]
        )
        required_keys = sorted(set(required_keys))
        configured_keys = await self.repo.configured_integrations(required_keys)
        for key in sorted(set(required_keys) - configured_keys):
            issues.append(self._issue("INTEGRATION_NOT_READY", "integration_requirements", key))

        try:
            active_kb_vector = await self.repo.active_kb_vector()
        except ValueError as exc:
            issues.append(self._issue("ACTIVE_KB_NOT_PINNED", "active_kb_vector", str(exc)))
            active_kb_vector = ()
        validation = InstallationManifestValidation(
            revision_id=revision.id,
            validator_version=VALIDATOR_VERSION,
            is_valid=not issues,
            issues=issues,
            reference_snapshot={
                "persona_version_id": str(revision.persona_version_id),
                "template_version_ids": sorted(expected_refs),
                "integration_keys": required_keys,
                "authentication_policy_checksum": revision.authentication_policy_checksum,
                "workflow_version_checksum": revision.workflow_version_checksum,
            },
            manifest_checksum=revision.manifest_checksum,
            pack_contract_hash=revision.pack_contract_hash,
            persona_checksum=persona_checksum,
            workflow_policy_checksum=revision.workflow_policy_checksum,
            provider_policy_checksum=revision.provider_policy_checksum,
            authentication_policy_checksum=revision.authentication_policy_checksum,
            workflow_version_checksum=revision.workflow_version_checksum,
            template_checksums=template_checksums,
            active_kb_vector=[list(item) for item in active_kb_vector],
            validated_by=actor_id,
        )
        self.db.add(validation)
        await self.db.flush()
        if state and state.current_revision_id == revision.id and validation.is_valid:
            state.validated_revision_id = revision.id
            if state.active_revision_id is None:
                state.lifecycle = InstallationLifecycle.validated.value
            state.lock_version += 1
            state.updated_at = func.now()
        await record_audit(
            self.db,
            action="validate_installation_revision",
            actor_id=actor_id,
            target_type="installation_revision",
            target_id=str(revision.id),
            payload={"is_valid": validation.is_valid, "issue_count": len(issues)},
        )
        if commit:
            await self.db.commit()
            await self._invalidate_cache_safely()
            await self.db.refresh(validation)
        if issues:
            raise self._error(
                "Installation revision validation failed",
                "INSTALLATION_VALIDATION_FAILED",
                lifecycle,
                status_code=422,
                issues=issues,
            )
        return validation

    async def activate_revision(
        self, revision_id: uuid.UUID, actor_id: uuid.UUID
    ) -> ActiveInstallation:
        await self.repo.acquire_authority_lock()
        state = await self.repo.get_state(for_update=True)
        lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
        if state is None:
            raise self._error(
                "Installation is not configured", "INSTALLATION_NOT_ACTIVE", lifecycle
            )
        return await self._activate_locked(state, revision_id, actor_id, rollback=False)

    async def rollback_revision(
        self, revision_id: uuid.UUID, actor_id: uuid.UUID
    ) -> ActiveInstallation:
        await self.repo.acquire_authority_lock()
        state = await self.repo.get_state(for_update=True)
        lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
        if state is None or state.active_revision_id is None:
            raise self._error("Installation is not active", "INSTALLATION_NOT_ACTIVE", lifecycle)
        target = await self._revision_or_error(revision_id, lifecycle)
        active = await self._revision_or_error(state.active_revision_id, lifecycle)
        if target.id == active.id:
            raise self._error(
                "Revision is already active",
                "INSTALLATION_CONFLICT",
                lifecycle,
            )
        if target.pack_key != active.pack_key:
            raise self._error(
                "Rollback cannot change the activated industry pack",
                "INSTALLATION_PACK_LOCKED",
                lifecycle,
            )
        return await self._activate_locked(state, revision_id, actor_id, rollback=True)

    async def suspend(self, actor_id: uuid.UUID) -> InstallationState:
        await self.repo.acquire_authority_lock()
        state = await self.repo.get_state(for_update=True)
        lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
        if state is None or state.active_revision_id is None:
            raise self._error("Installation is not active", "INSTALLATION_NOT_ACTIVE", lifecycle)
        if state.lifecycle != InstallationLifecycle.suspended.value:
            state.lifecycle = InstallationLifecycle.suspended.value
            state.authority_generation += 1
            state.lock_version += 1
            state.suspended_at = datetime.now(UTC)
            state.suspended_by = actor_id
            await self._audit_state("suspend_installation", state, actor_id)
            await self.db.commit()
            await self._invalidate_cache_safely()
            await self.db.refresh(state)
        return state

    async def resume(self, actor_id: uuid.UUID) -> ActiveInstallation:
        await self.repo.acquire_authority_lock()
        state = await self.repo.get_state(for_update=True)
        lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
        if (
            state is None
            or state.lifecycle != InstallationLifecycle.suspended.value
            or state.active_revision_id is None
        ):
            raise self._error("Installation is not suspended", "INSTALLATION_CONFLICT", lifecycle)
        validation = await self._find_current_validation(state.active_revision_id)
        if validation is None:
            raise self._error(
                "Active revision must be revalidated before resume",
                "INSTALLATION_VALIDATION_FAILED",
                lifecycle,
                status_code=422,
            )
        state.lifecycle = InstallationLifecycle.active.value
        state.authority_generation += 1
        state.lock_version += 1
        state.suspended_at = None
        state.suspended_by = None
        await self._audit_state("resume_installation", state, actor_id)
        await self.db.commit()
        await self._invalidate_cache_safely()
        return await self._active_context(state, validation)

    async def resolve_active(self) -> ActiveInstallation | None:
        state = await self.repo.get_state()
        if (
            state is None
            or state.lifecycle != InstallationLifecycle.active.value
            or state.active_revision_id is None
            or state.active_validation_id is None
        ):
            return None
        revision = await self.repo.get_revision(state.active_revision_id)
        if revision is None:
            return None
        try:
            pack = self.registry.get_pack(revision.pack_key)
        except ValueError:
            return None
        if (
            not pack.runtime_ready
            or pack.version != revision.pack_version
            or self.registry.pack_contract_hash(pack.key) != revision.pack_contract_hash
        ):
            return None
        validation = await self.db.get(InstallationManifestValidation, state.active_validation_id)
        if validation is None or not await self._validation_is_current(
            revision.id, validation, require_kb_snapshot=False
        ):
            return None
        try:
            active_kb_vector = await self.repo.active_kb_vector()
        except ValueError:
            return None
        expected = await self._active_context(
            state,
            validation,
            active_kb_vector=active_kb_vector,
            write_cache=False,
        )
        cached = await get_cached_fingerprint(revision.id, state.authority_generation)
        if cached is not None and cached.checksum() == expected.fingerprint.checksum():
            return ActiveInstallation(revision=revision, fingerprint=cached)
        return await self._active_context(state, validation, active_kb_vector=active_kb_vector)

    async def require_active(self) -> ActiveInstallation:
        active = await self.resolve_active()
        if active is None:
            state = await self.repo.get_state()
            lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
            raise self._error(
                "Installation is not active",
                "INSTALLATION_NOT_ACTIVE",
                lifecycle,
            )
        return active

    async def assert_current(self, fingerprint: RuntimeAuthorityFingerprint) -> None:
        state = await self.repo.get_state()
        current: RuntimeAuthorityFingerprint | None = None
        if (
            state is not None
            and state.lifecycle == InstallationLifecycle.active.value
            and state.active_revision_id is not None
            and state.active_validation_id is not None
        ):
            validation = await self.db.get(
                InstallationManifestValidation, state.active_validation_id
            )
            if validation is not None and await self._validation_is_current(
                state.active_revision_id, validation, require_kb_snapshot=False
            ):
                try:
                    active_kb_vector = await self.repo.active_kb_vector()
                except ValueError:
                    active_kb_vector = ()
                    validation = None
                if validation is None:
                    current = None
                else:
                    current = (
                        await self._active_context(
                            state,
                            validation,
                            active_kb_vector=active_kb_vector,
                            write_cache=False,
                        )
                    ).fingerprint
        if current is None or current.checksum() != fingerprint.checksum():
            raise self._error(
                "Runtime authority changed; retry against the current installation",
                "INSTALLATION_CONFLICT",
                state.lifecycle if state else InstallationLifecycle.unconfigured.value,
            )

    async def runtime_stamp_is_current(self, stamp: RuntimeAuthorityStamp) -> bool:
        """Return whether a durable command still matches the active authority exactly."""
        active = await self.resolve_active()
        return active is not None and active.fingerprint.stamp() == stamp

    async def runtime_view(self) -> InstallationRuntimeOut:
        state = await self.repo.get_state()
        if state is None:
            draft = await self.repo.get_setup_draft()
            return InstallationRuntimeOut(
                lifecycle=(
                    InstallationLifecycle.draft.value
                    if draft is not None
                    else InstallationLifecycle.unconfigured.value
                ),
                authority_generation=0,
                revision_id=None,
                pack_key=None,
                pack_version=None,
                pack_contract_hash=None,
                manifest_checksum=None,
                customer_identity=None,
                branding=None,
                locale=None,
                timezone=None,
                currency=None,
                terminology=None,
                capability_ids=[],
                readiness_code="SETUP_REQUIRED",
            )
        revision_id = state.active_revision_id
        if revision_id is None:
            return InstallationRuntimeOut(
                lifecycle=state.lifecycle,
                authority_generation=state.authority_generation,
                revision_id=None,
                pack_key=None,
                pack_version=None,
                pack_contract_hash=None,
                manifest_checksum=None,
                customer_identity=None,
                branding=None,
                locale=None,
                timezone=None,
                currency=None,
                terminology=None,
                capability_ids=[],
                readiness_code="SETUP_REQUIRED",
            )
        revision = await self._revision_or_error(revision_id, state.lifecycle)
        lifecycle, readiness = await self._runtime_readiness(state, revision)
        return InstallationRuntimeOut(
            lifecycle=lifecycle,
            authority_generation=state.authority_generation,
            revision_id=revision.id,
            pack_key=revision.pack_key,
            pack_version=revision.pack_version,
            pack_contract_hash=revision.pack_contract_hash,
            manifest_checksum=revision.manifest_checksum,
            customer_identity=self._public_mapping(
                revision.customer_identity, PUBLIC_CUSTOMER_IDENTITY_KEYS
            ),
            branding=self._public_mapping(revision.branding, PUBLIC_BRANDING_KEYS),
            locale=revision.locale,
            timezone=revision.timezone,
            currency=revision.currency,
            terminology={
                str(key): value
                for key, value in revision.terminology.items()
                if isinstance(value, str) and not self._secret_like_key(str(key))
            },
            capability_ids=revision.capability_ids,
            readiness_code=readiness,
        )

    async def admin_view(self) -> InstallationAdminOut:
        state = await self.repo.get_state()
        if state is None:
            draft = await self.repo.get_setup_draft()
            return InstallationAdminOut(
                lifecycle=(
                    InstallationLifecycle.draft.value
                    if draft is not None
                    else InstallationLifecycle.unconfigured.value
                ),
                authority_generation=0,
                lock_version=0,
                current_revision=None,
                active_revision_id=None,
                active_validation=None,
                current_validation=None,
                readiness_code="SETUP_REQUIRED",
            )
        current = await self._revision_or_error(state.current_revision_id, state.lifecycle)
        validation = (
            await self.db.get(InstallationManifestValidation, state.active_validation_id)
            if state.active_validation_id
            else None
        )
        current_validation = await self._find_current_validation(current.id)
        readiness_revision = current
        if state.active_revision_id is not None:
            readiness_revision = await self._revision_or_error(
                state.active_revision_id, state.lifecycle
            )
        lifecycle, readiness = await self._runtime_readiness(state, readiness_revision)
        return InstallationAdminOut(
            lifecycle=lifecycle,
            authority_generation=state.authority_generation,
            lock_version=state.lock_version,
            current_revision=InstallationRevisionOut.model_validate(current),
            active_revision_id=state.active_revision_id,
            active_validation=(
                InstallationValidationOut.model_validate(validation) if validation else None
            ),
            current_validation=(
                InstallationValidationOut.model_validate(current_validation)
                if current_validation
                else None
            ),
            readiness_code=readiness,
        )

    async def _activate_locked(
        self,
        state: InstallationState,
        revision_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        rollback: bool,
    ) -> ActiveInstallation:
        revision = await self._revision_or_error(revision_id, state.lifecycle)
        if not rollback and state.active_revision_id == revision.id:
            raise self._error(
                "Revision is already active",
                "INSTALLATION_CONFLICT",
                state.lifecycle,
            )
        if not rollback and (
            state.current_revision_id != revision.id or state.validated_revision_id != revision.id
        ):
            raise self._error(
                "Only the current validated revision can be activated",
                "INSTALLATION_CONFLICT",
                state.lifecycle,
            )
        validation = await self._find_current_validation(revision_id)
        if validation is None:
            raise self._error(
                "Revision has no current successful validation evidence",
                "INSTALLATION_VALIDATION_FAILED",
                state.lifecycle,
                status_code=422,
            )
        pack = self.registry.get_pack(revision.pack_key)
        await self.repo.lock_operational_writers()
        incompatible_data = (await self.repo.operational_data_kinds()) - set(
            pack.compatible_operational_data
        )
        if incompatible_data:
            raise self._error(
                f"Industry pack is incompatible with existing data: {sorted(incompatible_data)}",
                "INSTALLATION_PACK_LOCKED",
                state.lifecycle,
            )
        if not pack.runtime_ready:
            raise self._error(
                "Industry pack runtime enforcement is not ready",
                "INSTALLATION_RUNTIME_NOT_READY",
                state.lifecycle,
            )
        old_active = state.active_revision_id
        state.previous_active_revision_id = old_active
        state.current_revision_id = revision.id
        state.validated_revision_id = revision.id
        state.active_revision_id = revision.id
        state.active_validation_id = validation.id
        state.lifecycle = InstallationLifecycle.active.value
        state.authority_generation += 1
        state.lock_version += 1
        state.activated_at = datetime.now(UTC)
        state.activated_by = actor_id
        state.suspended_at = None
        state.suspended_by = None
        await self._audit_state(
            "rollback_installation_revision" if rollback else "activate_installation_revision",
            state,
            actor_id,
        )
        await self.db.commit()
        await self._invalidate_cache_safely()
        return await self._active_context(state, validation)

    async def _validation_is_current(
        self,
        revision_id: uuid.UUID,
        validation: InstallationManifestValidation,
        *,
        require_kb_snapshot: bool = True,
    ) -> bool:
        revision = await self.repo.get_revision(revision_id)
        persona = (
            await self.repo.get_persona_version(revision.persona_version_id) if revision else None
        )
        if revision is None or persona is None:
            return False
        if (
            revision.workflow_version_id is None
            or revision.workflow_version_checksum is None
            or validation.workflow_version_checksum != revision.workflow_version_checksum
        ):
            return False
        workflow_version = await self.db.get(CaseWorkflowVersion, revision.workflow_version_id)
        if (
            workflow_version is None
            or workflow_version.checksum != revision.workflow_version_checksum
            or workflow_version.pack_key != revision.pack_key
            or workflow_version.workflow_key != revision.workflow_policy.get("workflow_id")
        ):
            return False
        try:
            pack = self.registry.get_pack(revision.pack_key)
            registry_current = (
                pack.version == revision.pack_version
                and self.registry.pack_contract_hash(pack.key) == revision.pack_contract_hash
            )
        except ValueError:
            registry_current = False
        expected_templates = {
            str(item["version_id"]): str(item["checksum"])
            for item in revision.template_version_refs
        }
        actual_templates = await self.repo.template_checksums(
            [uuid.UUID(version_id) for version_id in expected_templates]
        )
        templates_current = all(
            actual_templates.get(version_id) == checksum
            for version_id, checksum in expected_templates.items()
        )
        kb_current = not require_kb_snapshot or tuple(
            tuple(item) for item in validation.active_kb_vector
        ) == (await self.repo.active_kb_vector())
        required_integrations = [str(item["key"]) for item in revision.integration_requirements]
        required_integrations.extend(
            [
                str(revision.provider_policy["chat_integration_key"]),
                str(revision.provider_policy["embedding_integration_key"]),
            ]
        )
        required_integrations = sorted(set(required_integrations))
        integrations_current = set(required_integrations) <= (
            await self.repo.configured_integrations(required_integrations)
        )
        return (
            validation.is_valid
            and registry_current
            and templates_current
            and kb_current
            and integrations_current
            and validation.manifest_checksum == revision.manifest_checksum
            and validation.pack_contract_hash == revision.pack_contract_hash
            and validation.persona_checksum == persona.checksum
            and validation.workflow_policy_checksum == revision.workflow_policy_checksum
            and validation.provider_policy_checksum == revision.provider_policy_checksum
            and revision.authentication_policy is not None
            and revision.authentication_policy_checksum is not None
            and validation.authentication_policy_checksum == revision.authentication_policy_checksum
        )

    async def _find_current_validation(
        self, revision_id: uuid.UUID
    ) -> InstallationManifestValidation | None:
        for validation in await self.repo.get_valid_validations(revision_id):
            if await self._validation_is_current(revision_id, validation):
                return validation
        return None

    async def _active_context(
        self,
        state: InstallationState,
        validation: InstallationManifestValidation,
        *,
        active_kb_vector: tuple[tuple[str, str], ...] | None = None,
        write_cache: bool = True,
    ) -> ActiveInstallation:
        revision = await self._revision_or_error(validation.revision_id, state.lifecycle)
        if validation.authentication_policy_checksum is None:
            raise self._error(
                "Authentication authority must be upgraded before runtime use",
                "INSTALLATION_VALIDATION_FAILED",
                InstallationLifecycle.upgrade_required.value,
                status_code=422,
            )
        if validation.workflow_version_checksum is None:
            raise self._error(
                "Workflow authority must be upgraded before runtime use",
                "INSTALLATION_VALIDATION_FAILED",
                InstallationLifecycle.upgrade_required.value,
                status_code=422,
            )
        fingerprint = RuntimeAuthorityFingerprint(
            authority_generation=state.authority_generation,
            revision_id=revision.id,
            manifest_checksum=validation.manifest_checksum,
            pack_contract_hash=validation.pack_contract_hash,
            persona_checksum=validation.persona_checksum,
            workflow_policy_checksum=validation.workflow_policy_checksum,
            provider_policy_checksum=validation.provider_policy_checksum,
            authentication_policy_checksum=validation.authentication_policy_checksum,
            template_checksums=dict(validation.template_checksums),
            active_kb_vector=(
                active_kb_vector
                if active_kb_vector is not None
                else tuple(tuple(item) for item in validation.active_kb_vector)
            ),
        )
        if write_cache:
            try:
                await cache_fingerprint(fingerprint)
            except Exception:  # noqa: BLE001 - cache cannot change committed authority
                logger.warning("installation authority cache write failed", exc_info=True)
        return ActiveInstallation(revision=revision, fingerprint=fingerprint)

    async def _revision_or_error(
        self, revision_id: uuid.UUID, lifecycle: str
    ) -> InstallationManifestRevision:
        revision = await self.repo.get_revision(revision_id)
        if revision is None:
            raise self._error(
                "Installation revision not found",
                "INSTALLATION_REVISION_NOT_FOUND",
                lifecycle,
                status_code=404,
            )
        return revision

    async def _runtime_readiness(
        self, state: InstallationState, revision: InstallationManifestRevision
    ) -> tuple[str, str]:
        if (
            revision.authentication_policy is None
            or revision.authentication_policy_checksum is None
            or sha256_json(revision.authentication_policy)
            != revision.authentication_policy_checksum
        ):
            return InstallationLifecycle.upgrade_required.value, "UPGRADE_REQUIRED"
        if revision.workflow_version_id is None or revision.workflow_version_checksum is None:
            return InstallationLifecycle.upgrade_required.value, "UPGRADE_REQUIRED"
        try:
            pack = self.registry.get_pack(revision.pack_key)
        except ValueError:
            return InstallationLifecycle.upgrade_required.value, "UPGRADE_REQUIRED"
        if (
            pack.version != revision.pack_version
            or self.registry.pack_contract_hash(pack.key) != revision.pack_contract_hash
        ):
            return InstallationLifecycle.upgrade_required.value, "UPGRADE_REQUIRED"
        if not pack.runtime_ready:
            return state.lifecycle, "RUNTIME_NOT_READY"
        if state.lifecycle == InstallationLifecycle.suspended.value:
            return state.lifecycle, "SUSPENDED"
        if state.lifecycle == InstallationLifecycle.active.value:
            if state.active_validation_id is None or state.active_revision_id != revision.id:
                return state.lifecycle, "VALIDATION_REQUIRED"
            validation = await self.db.get(
                InstallationManifestValidation, state.active_validation_id
            )
            if validation is None:
                return state.lifecycle, "VALIDATION_REQUIRED"
            try:
                evidence_current = await self._validation_is_current(
                    revision.id, validation, require_kb_snapshot=False
                )
                await self.repo.active_kb_vector()
            except ValueError:
                evidence_current = False
            if not evidence_current:
                return state.lifecycle, "VALIDATION_REQUIRED"
            return state.lifecycle, "READY"
        return state.lifecycle, "SETUP_REQUIRED"

    def _assert_expected_lock(
        self,
        state: InstallationState | None,
        expected_lock_version: int,
        lifecycle: str,
    ) -> None:
        actual_lock_version = state.lock_version if state is not None else 0
        if expected_lock_version != actual_lock_version:
            raise self._error(
                "Installation changed since it was loaded; reload before saving",
                "INSTALLATION_CONFLICT",
                lifecycle,
            )

    async def _audit_state(
        self, action: str, state: InstallationState, actor_id: uuid.UUID
    ) -> None:
        await record_audit(
            self.db,
            action=action,
            actor_id=actor_id,
            target_type="installation",
            target_id="1",
            payload={
                "active_revision_id": str(state.active_revision_id),
                "authority_generation": state.authority_generation,
            },
        )

    async def _invalidate_cache_safely(self) -> None:
        try:
            await invalidate_installation_cache()
        except Exception:  # noqa: BLE001 - Redis is never installation authority
            logger.warning("installation authority cache invalidation failed", exc_info=True)

    @staticmethod
    def _issue(code: str, path: str, message: str | None = None) -> dict[str, str | None]:
        return {"code": code, "message": message or code.replace("_", " ").title(), "path": path}

    @classmethod
    def _contains_secret_key(cls, value: object) -> bool:
        if isinstance(value, dict):
            return any(
                cls._secret_like_key(str(key)) or cls._contains_secret_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(cls._contains_secret_key(item) for item in value)
        return False

    @classmethod
    def _contains_secret_value(cls, value: object) -> bool:
        if isinstance(value, dict):
            return any(cls._contains_secret_value(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._contains_secret_value(item) for item in value)
        if hasattr(value, "model_dump"):
            return cls._contains_secret_value(value.model_dump(mode="json"))
        return isinstance(value, str) and bool(_SECRET_VALUE_PATTERN.search(value.strip()))

    @staticmethod
    def _secret_like_key(key: str) -> bool:
        normalized = "".join(character for character in key.lower() if character.isalnum())
        return (
            "secret" in normalized
            or normalized.endswith("token")
            or normalized.endswith("apikey")
            or normalized.endswith("password")
            or normalized.endswith("credential")
            or normalized.endswith("privatekey")
        )

    @staticmethod
    def _public_mapping(value: dict, allowed_keys: set[str]) -> dict:
        return {key: item for key, item in value.items() if key in allowed_keys}

    @staticmethod
    def _error(
        message: str,
        code: str,
        lifecycle: str,
        *,
        status_code: int = 409,
        issues: list[dict[str, str | None]] | None = None,
    ) -> InstallationError:
        return InstallationError(
            message,
            code=code,
            lifecycle=lifecycle,
            status_code=status_code,
            issues=issues,
        )
