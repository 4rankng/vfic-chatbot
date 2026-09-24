"""Admin and runtime projections of the installation state.

Reads only: the operator-facing runtime view, the admin view with its
readiness code, and the readiness derivation they share. Public fields are
projected through the allow-lists so secrets and non-public identity fields
never reach a projection. Mixed into ``InstallationService``.
"""

from __future__ import annotations

from app.installation.domain.projection import (
    project_public_mapping,
    project_public_terminology,
)
from app.models.installation import (
    InstallationLifecycle,
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationState,
)
from app.schemas.installation import (
    InstallationAdminOut,
    InstallationRevisionOut,
    InstallationRuntimeOut,
    InstallationValidationOut,
)
from app.services.installation.hashing import sha256_json

PUBLIC_CUSTOMER_IDENTITY_KEYS = frozenset(
    {
        "display_name",
        "legal_name",
        "support_name",
        "support_email",
        "support_phone",
        "website_url",
        "address",
    }
)
PUBLIC_BRANDING_KEYS = frozenset(
    {
        "app_name",
        "primary_color",
        "secondary_color",
    }
)


class ProjectionMixin:
    """Runtime/admin projections and the readiness derivation."""

    async def runtime_view(self) -> InstallationRuntimeOut:
        state = await self.repo.get_state()
        if state is None:
            return InstallationRuntimeOut(
                lifecycle=InstallationLifecycle.unconfigured.value,
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
                legacy_workspace=await self.repo.has_legacy_workspace(),
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
                legacy_workspace=False,
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
            terminology=project_public_terminology(revision.terminology),
            capability_ids=revision.capability_ids,
            readiness_code=readiness,
            legacy_workspace=False,
        )

    async def admin_view(self) -> InstallationAdminOut:
        state = await self.repo.get_state()
        if state is None:
            return InstallationAdminOut(
                lifecycle=InstallationLifecycle.unconfigured.value,
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

    @staticmethod
    def _public_mapping(value: dict, allowed_keys: set[str] | frozenset[str]) -> dict:
        return project_public_mapping(value, allowed_keys)
