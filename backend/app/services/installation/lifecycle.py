"""Authority-locked lifecycle transitions and runtime authority resolution.

Every mutation that moves the installation lifecycle (activate / rollback /
suspend / resume) runs under the repository's authority lock, bumps the
authority generation, and invalidates the runtime cache fence in the same
transaction. The resolution half (``resolve_active`` / ``require_active`` /
``assert_current`` / ``runtime_stamp_is_current``) is the per-turn hot path:
cache-first, with the revision row, pack contract, and live KB vector staying
DB-backed. Mixed into ``InstallationService``.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING
from datetime import UTC, datetime

from app.capabilities.contracts import IndustryPackDefinition
from app.models.installation import (
    InstallationLifecycle,
    InstallationManifestRevision,
    InstallationManifestValidation,
    InstallationState,
)
from app.services.audit_service import record_audit
from app.services.installation.authority import RuntimeAuthorityFingerprint, RuntimeAuthorityStamp
from app.services.installation.runtime import (
    cache_fingerprint,
    get_cached_fingerprint,
    invalidate_installation_cache,
)

logger = logging.getLogger(__name__)


class LifecycleMixin:
    """Authority-locked transitions plus the runtime authority hot path."""

    if TYPE_CHECKING:
        # Supplied by InstallationService, the class that mixes these in.
        # Declarations only: TYPE_CHECKING is False at runtime, so nothing here
        # is ever assigned and the composed class stays the single source of
        # truth for the contract.
        db: AsyncSession
        repo: InstallationRepository
        registry: CapabilityRegistry

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.capabilities.registry import CapabilityRegistry
        from app.services.installation.repository import InstallationRepository
        from app.shared.domain.errors import InstallationError

        @staticmethod
        def _error(
            message: str,
            code: str,
            lifecycle: str,
            *,
            status_code: int = 409,
            issues: list[dict[str, str | None]] | None = None,
        ) -> InstallationError: ...

        async def _revision_or_error(
            self, revision_id: uuid.UUID, lifecycle: str
        ) -> InstallationManifestRevision: ...

        async def _validation_is_current(
            self,
            revision_id: uuid.UUID,
            validation: InstallationManifestValidation,
            *,
            require_kb_snapshot: bool = True,
        ) -> bool: ...

        async def _find_current_validation(
            self, revision_id: uuid.UUID
        ) -> InstallationManifestValidation | None: ...

        from app.services.installation.service import ActiveInstallation

    async def activate_revision(
        self, revision_id: uuid.UUID, actor_id: uuid.UUID
    ) -> "ActiveInstallation":  # composed attribute, declared under TYPE_CHECKING
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
    ) -> "ActiveInstallation":  # composed attribute, declared under TYPE_CHECKING
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

    async def resume(self, actor_id: uuid.UUID) -> "ActiveInstallation":  # composed attribute, declared under TYPE_CHECKING
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

    async def resolve_active(self) -> "ActiveInstallation | None":  # composed attribute, declared under TYPE_CHECKING
        state = await self.repo.get_state()
        if (
            state is None
            or state.lifecycle != InstallationLifecycle.active.value
            or state.active_revision_id is None
            or state.active_validation_id is None
        ):
            return None
        # Cache-first: every lifecycle mutation advances both the identity
        # (active revision, authority generation) and the cache namespace
        # version via invalidate_installation_cache(), so a hit for the
        # current identity is the fingerprint the full derivation would
        # rebuild. The revision row, pack contract, and live KB vector stay
        # DB-backed on this path: the KB vector is the one fingerprint input
        # that moves on routine KB publishes, which do not bump the
        # installation namespace.
        revision: InstallationManifestRevision | None = None
        cached = await get_cached_fingerprint(state.active_revision_id, state.authority_generation)
        if cached is not None:
            revision = await self.repo.get_revision(state.active_revision_id)
            if revision is None or self._registry_pack_current(revision) is None:
                return None
            try:
                kb_unchanged = cached.active_kb_vector == await self.repo.active_kb_vector()
            except ValueError:
                return None
            if kb_unchanged:
                from app.services.installation.service import ActiveInstallation

                return ActiveInstallation(revision=revision, fingerprint=cached)
        if revision is None:
            revision = await self.repo.get_revision(state.active_revision_id)
        if revision is None or self._registry_pack_current(revision) is None:
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
        return await self._active_context(state, validation, active_kb_vector=active_kb_vector)

    async def require_active(self) -> "ActiveInstallation":  # composed attribute, declared under TYPE_CHECKING
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

    async def _activate_locked(
        self,
        state: InstallationState,
        revision_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        rollback: bool,
    ) -> "ActiveInstallation":  # composed attribute, declared under TYPE_CHECKING
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

    def _registry_pack_current(
        self, revision: InstallationManifestRevision
    ) -> IndustryPackDefinition | None:
        """Return the registry pack only while it matches the revision contract."""
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
        return pack

    async def _active_context(
        self,
        state: InstallationState,
        validation: InstallationManifestValidation,
        *,
        active_kb_vector: tuple[tuple[str, str], ...] | None = None,
        write_cache: bool = True,
    ) -> "ActiveInstallation":  # composed attribute, declared under TYPE_CHECKING
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
        from app.services.installation.service import ActiveInstallation

        return ActiveInstallation(revision=revision, fingerprint=fingerprint)

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
