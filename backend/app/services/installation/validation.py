"""Revision CRUD and fail-closed validation for installation manifests.

Everything that turns a draft body into a checksummed revision row and every
check that decides whether validation evidence is still current lives here:
the two writer endpoints' logic, the secret-scanning gate, and the
``_validation_is_current`` currency battery the lifecycle transitions and the
runtime resolution both depend on. Mixed into ``InstallationService``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func

from app.installation.domain.projection import (
    contains_secret_key,
    contains_secret_value,
    secret_like_key,
)
from app.models.case_workflow import CaseWorkflowVersion
from app.models.installation import (
    InstallationLifecycle,
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationState,
)
from app.services.audit_service import record_audit
from app.services.installation.catalog import (
    CHAT_INTEGRATION_REFERENCES,
    EMBEDDING_INTEGRATION_REFERENCES,
    integration_reference_ids,
)
from app.services.installation.hashing import sha256_json
from app.schemas.installation import InstallationRevisionCreate

VALIDATOR_VERSION = "1"


class ValidationMixin:
    """Revision creation, revision validation, and evidence-currency checks."""

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

    @staticmethod
    def _issue(code: str, path: str, message: str | None = None) -> dict[str, str | None]:
        return {"code": code, "message": message or code.replace("_", " ").title(), "path": path}

    @classmethod
    def _contains_secret_key(cls, value: object) -> bool:
        return contains_secret_key(value)

    @classmethod
    def _contains_secret_value(cls, value: object) -> bool:
        return contains_secret_value(value)

    @staticmethod
    def _secret_like_key(key: str) -> bool:
        return secret_like_key(key)
