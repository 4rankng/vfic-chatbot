"""Database-backed installation authoring workspace and atomic finalization."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.registry import CapabilityRegistry, get_capability_registry
from app.models.installation import InstallationLifecycle, InstallationSetupDraft
from app.schemas.installation import (
    ISO_4217_CURRENCY_CODES,
    SETUP_SECTION_NAMES,
    SHIPPED_LOCALES,
    CapabilityCatalogItem,
    InstallationCatalogOut,
    InstallationIssue,
    InstallationRevisionOut,
    InstallationSetupDraftFinalize,
    InstallationSetupDraftOut,
    InstallationSetupDraftPayload,
    InstallationSetupDraftSave,
    PackCatalogItem,
    WorkflowCatalogItem,
    AuthoredWorkflowVersionCatalogItem,
)
from app.models.case_workflow import CaseWorkflowVersion
from app.services.errors import InstallationError
from app.services.audit_service import record_audit
from app.services.installation.catalog import (
    AUTHENTICATION_METHODS,
    CHANNEL_CAPABILITY_REQUIREMENTS,
    CHAT_INTEGRATION_REFERENCES,
    EMBEDDING_INTEGRATION_REFERENCES,
    HANDOFF_MODES,
    integration_reference_ids,
)
from app.services.installation.repository import InstallationRepository
from app.services.installation.service import InstallationService


_SECRET_VALUE_PATTERN = re.compile(
    r"^(?:sk-|xox[a-z]*-|ghp_|github_pat_|AIza)|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
    re.IGNORECASE,
)


class InstallationSetupService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        self.db = db
        self.repo = InstallationRepository(db)
        self.registry = registry or get_capability_registry()

    async def view(self) -> InstallationSetupDraftOut:
        draft = await self.repo.get_setup_draft()
        state = await self.repo.get_state()
        payload = (
            InstallationSetupDraftPayload.model_validate(draft.payload)
            if draft is not None
            else InstallationSetupDraftPayload()
        )
        return self._draft_out(
            payload,
            draft.lock_version if draft is not None else 0,
            state.lock_version if state is not None else 0,
        )

    async def save(
        self, body: InstallationSetupDraftSave, actor_id: uuid.UUID
    ) -> InstallationSetupDraftOut:
        await self.repo.acquire_authority_lock()
        draft = await self.repo.get_setup_draft(for_update=True)
        state = await self.repo.get_state(for_update=True)
        lifecycle = (
            state.lifecycle
            if state is not None
            else (
                InstallationLifecycle.draft.value
                if draft is not None
                else InstallationLifecycle.unconfigured.value
            )
        )
        actual_lock = draft.lock_version if draft is not None else 0
        if body.expected_lock_version != actual_lock:
            raise self._error(
                "Setup draft changed since it was loaded; reload before saving",
                "INSTALLATION_CONFLICT",
                lifecycle,
            )
        self._validate_authoring_choices(body.payload, lifecycle, require_complete=False)
        payload = body.payload.model_dump(mode="json", exclude_none=True)
        if self._contains_secret_value(payload):
            raise self._error(
                "Setup draft must reference encrypted integrations, not contain credentials",
                "INSTALLATION_VALIDATION_FAILED",
                lifecycle,
                status_code=422,
                issues=[self._issue("PLAINTEXT_SECRET_FORBIDDEN", "payload")],
            )
        if draft is None:
            draft = InstallationSetupDraft(
                singleton_id=1,
                payload=payload,
                lock_version=1,
                updated_by=actor_id,
            )
            self.db.add(draft)
        else:
            draft.payload = payload
            draft.lock_version += 1
            draft.updated_by = actor_id
            draft.updated_at = func.now()
        await record_audit(
            self.db,
            action="save_installation_setup_draft",
            actor_id=actor_id,
            target_type="installation_setup_draft",
            target_id="1",
            payload={
                "lock_version": draft.lock_version,
                "completed_sections": sorted(
                    section
                    for section in SETUP_SECTION_NAMES
                    if getattr(body.payload, section) is not None
                ),
            },
        )
        await self.db.commit()
        await self.db.refresh(draft)
        return self._draft_out(
            body.payload,
            draft.lock_version,
            state.lock_version if state is not None else 0,
        )

    async def finalize(
        self, body: InstallationSetupDraftFinalize, actor_id: uuid.UUID
    ) -> InstallationRevisionOut:
        try:
            await self.repo.acquire_authority_lock()
            draft = await self.repo.get_setup_draft(for_update=True)
            state = await self.repo.get_state(for_update=True)
            lifecycle = state.lifecycle if state else InstallationLifecycle.unconfigured.value
            if draft is None:
                raise self._error(
                    "Setup draft does not exist",
                    "INSTALLATION_VALIDATION_FAILED",
                    lifecycle,
                    status_code=422,
                    issues=[self._issue("SETUP_DRAFT_REQUIRED", "payload")],
                )
            if draft.lock_version != body.expected_draft_lock_version:
                raise self._error(
                    "Setup draft changed since it was loaded; reload before finalizing",
                    "INSTALLATION_CONFLICT",
                    lifecycle,
                )
            installation_lock = state.lock_version if state is not None else 0
            if installation_lock != body.expected_installation_lock_version:
                raise self._error(
                    "Installation changed since it was loaded; reload before finalizing",
                    "INSTALLATION_CONFLICT",
                    lifecycle,
                )

            payload = InstallationSetupDraftPayload.model_validate(draft.payload)
            self._validate_authoring_choices(payload, lifecycle, require_complete=True)
            assert payload.persona is not None
            persona_version = await self.repo.get_persona_version(
                payload.persona.persona_version_id
            )
            if persona_version is None or persona_version.checksum != payload.persona.checksum:
                raise self._error(
                    "Persona version checksum is not current",
                    "INSTALLATION_VALIDATION_FAILED",
                    lifecycle,
                    status_code=422,
                    issues=[self._issue("PERSONA_CHECKSUM_MISMATCH", "persona")],
                )
            assert payload.workflow is not None
            workflow_policy = payload.workflow.workflow_policy
            if (
                workflow_policy.workflow_version_id is None
                or workflow_policy.workflow_version_checksum is None
            ):
                raise self._error(
                    "An immutable workflow version is required before finalization",
                    "INSTALLATION_VALIDATION_FAILED",
                    lifecycle,
                    status_code=422,
                    issues=[
                        self._issue(
                            "WORKFLOW_VERSION_REQUIRED",
                            "workflow.workflow_policy.workflow_version_id",
                        )
                    ],
                )

            revision_body = payload.to_revision_create(
                expected_lock_version=body.expected_installation_lock_version
            )
            installation = InstallationService(self.db, registry=self.registry)
            revision = await installation.create_revision(revision_body, actor_id, commit=False)
            await installation.validate_revision(revision.id, actor_id, commit=False)
            draft.lock_version += 1
            draft.updated_by = actor_id
            draft.updated_at = func.now()
            await self.db.commit()
            await installation._invalidate_cache_safely()
            await self.db.refresh(revision)
            return InstallationRevisionOut.model_validate(revision)
        except Exception:
            await self.db.rollback()
            raise

    async def catalog(self) -> InstallationCatalogOut:
        packs = self.registry.packs()
        workflows = sorted({workflow for pack in packs for workflow in pack.workflow_ids})
        authored: list[CaseWorkflowVersion] = []
        if isinstance(self.db, AsyncSession):
            authored = list(
                await self.db.scalars(
                    select(CaseWorkflowVersion)
                    .order_by(
                        CaseWorkflowVersion.pack_key,
                        CaseWorkflowVersion.workflow_key,
                        CaseWorkflowVersion.version_no.desc(),
                    )
                    .limit(200)
                )
            )
        return InstallationCatalogOut(
            packs=[
                PackCatalogItem(
                    key=pack.key,
                    version=pack.version,
                    contract_hash=self.registry.pack_contract_hash(pack.key),
                    capability_ids=list(pack.capability_ids),
                    runtime_ready=pack.runtime_ready,
                    workflow_ids=list(pack.workflow_ids),
                    terminology_keys=list(pack.terminology_keys),
                )
                for pack in packs
            ],
            capabilities=[
                CapabilityCatalogItem(
                    id=capability.capability_id,
                    dependencies=list(capability.dependencies),
                )
                for capability in self.registry.capabilities()
            ],
            locales=list(SHIPPED_LOCALES),
            currencies=sorted(ISO_4217_CURRENCY_CODES),
            workflows=[
                WorkflowCatalogItem(id=workflow, handoff_modes=list(HANDOFF_MODES))
                for workflow in workflows
            ],
            authored_workflow_versions=[
                AuthoredWorkflowVersionCatalogItem.model_validate(item, from_attributes=True)
                for item in authored
            ],
            integration_keys=list(integration_reference_ids()),
            authentication_methods=list(AUTHENTICATION_METHODS),
        )

    def _validate_authoring_choices(
        self,
        payload: InstallationSetupDraftPayload,
        lifecycle: str,
        *,
        require_complete: bool,
    ) -> None:
        issues: list[dict[str, str | None]] = []
        if require_complete:
            for section in SETUP_SECTION_NAMES:
                if getattr(payload, section) is None:
                    issues.append(self._issue("SETUP_SECTION_REQUIRED", section))

        pack = None
        if payload.pack_capabilities is not None:
            selection = payload.pack_capabilities
            try:
                pack = self.registry.get_pack(selection.pack_key)
                self.registry.validate_selection(selection.pack_key, selection.capability_ids)
            except ValueError as exc:
                issues.append(self._issue("PACK_SELECTION_INVALID", "pack_capabilities", str(exc)))

        if pack is not None and payload.regional_terminology is not None:
            provided_terms = set(payload.regional_terminology.terminology)
            required_terms = set(pack.terminology_keys)
            unknown_terms = provided_terms - required_terms
            if unknown_terms:
                issues.append(
                    self._issue(
                        "TERMINOLOGY_KEY_INVALID",
                        "regional_terminology.terminology",
                        f"Keys are not supported by pack {pack.key}: {sorted(unknown_terms)}",
                    )
                )
            if require_complete and required_terms - provided_terms:
                issues.append(
                    self._issue(
                        "TERMINOLOGY_REQUIRED",
                        "regional_terminology.terminology",
                        f"Missing terminology keys: {sorted(required_terms - provided_terms)}",
                    )
                )
        if pack is not None and payload.workflow is not None:
            workflow_id = payload.workflow.workflow_policy.workflow_id
            if workflow_id not in pack.workflow_ids:
                issues.append(
                    self._issue(
                        "WORKFLOW_INVALID",
                        "workflow.workflow_policy.workflow_id",
                        f"Workflow is not supported by pack {pack.key}",
                    )
                )
        elif payload.workflow is not None:
            known_workflows = {
                workflow_id
                for known_pack in self.registry.packs()
                for workflow_id in known_pack.workflow_ids
            }
            if payload.workflow.workflow_policy.workflow_id not in known_workflows:
                issues.append(
                    self._issue(
                        "WORKFLOW_INVALID",
                        "workflow.workflow_policy.workflow_id",
                    )
                )

        providers = payload.providers_integrations
        if providers is not None:
            provider_policy = providers.provider_policy
            if provider_policy.chat_integration_key not in CHAT_INTEGRATION_REFERENCES:
                issues.append(
                    self._issue(
                        "INTEGRATION_REFERENCE_INVALID",
                        "providers_integrations.provider_policy.chat_integration_key",
                    )
                )
            if provider_policy.embedding_integration_key not in EMBEDDING_INTEGRATION_REFERENCES:
                issues.append(
                    self._issue(
                        "INTEGRATION_REFERENCE_INVALID",
                        "providers_integrations.provider_policy.embedding_integration_key",
                    )
                )
            unknown_refs = {
                requirement.key for requirement in providers.integration_requirements
            } - set(integration_reference_ids())
            if unknown_refs:
                issues.append(
                    self._issue(
                        "INTEGRATION_REFERENCE_INVALID",
                        "providers_integrations.integration_requirements",
                        f"Unknown integration references: {sorted(unknown_refs)}",
                    )
                )

        if pack is not None and providers is not None:
            required_refs = {
                reference
                for capability, reference in CHANNEL_CAPABILITY_REQUIREMENTS.items()
                if capability in payload.pack_capabilities.capability_ids
            }
            selected_refs = {item.key for item in providers.integration_requirements}
            missing_refs = required_refs - selected_refs
            if missing_refs:
                issues.append(
                    self._issue(
                        "INTEGRATION_REQUIRED_BY_CAPABILITY",
                        "providers_integrations.integration_requirements",
                        f"Missing integration references: {sorted(missing_refs)}",
                    )
                )

        if (
            require_complete
            and payload.pack_capabilities is not None
            and "knowledge" in payload.pack_capabilities.capability_ids
            and payload.knowledge_templates is not None
            and not payload.knowledge_templates.template_version_refs
        ):
            issues.append(
                self._issue(
                    "TEMPLATE_REQUIRED_BY_CAPABILITY",
                    "knowledge_templates.template_version_refs",
                )
            )

        if issues:
            raise self._error(
                "Setup draft validation failed",
                "INSTALLATION_VALIDATION_FAILED",
                lifecycle,
                status_code=422,
                issues=issues,
            )

    @classmethod
    def _contains_secret_value(cls, value: object) -> bool:
        if isinstance(value, dict):
            return any(cls._contains_secret_value(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._contains_secret_value(item) for item in value)
        return isinstance(value, str) and bool(_SECRET_VALUE_PATTERN.search(value.strip()))

    @staticmethod
    def _draft_out(
        payload: InstallationSetupDraftPayload,
        lock_version: int,
        installation_lock_version: int,
    ) -> InstallationSetupDraftOut:
        completion = {
            section: getattr(payload, section) is not None for section in SETUP_SECTION_NAMES
        }
        issues = [
            InstallationIssue(
                code="SETUP_SECTION_REQUIRED",
                message="Setup section is incomplete",
                path=section,
            )
            for section, complete in completion.items()
            if not complete
        ]
        return InstallationSetupDraftOut(
            payload=payload,
            lock_version=lock_version,
            installation_lock_version=installation_lock_version,
            section_completion=completion,
            issues=issues,
        )

    @staticmethod
    def _issue(code: str, path: str, message: str | None = None) -> dict[str, str | None]:
        return {"code": code, "message": message or code.replace("_", " ").title(), "path": path}

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
