"""Two-session proof that one installation revision advances the pointer once."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.shared.domain.errors import InstallationError
from app.services.installation.service import ActiveInstallation, InstallationService
from tests.integration.conftest import IntegrationDatabase
from tests.integration.test_installation_lifecycle import (
    _revision_body,
    _runtime_ready_registry,
    _seed_actor_and_workflow_pin,
)

pytestmark = pytest.mark.integration


async def test_two_sessions_cannot_advance_the_same_revision_twice(
    integration_database: IntegrationDatabase,
):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    registry = _runtime_ready_registry()
    try:
        async with sessions() as setup_session:
            actor, workflow_pin = await _seed_actor_and_workflow_pin(setup_session)
            setup_service = InstallationService(setup_session, registry=registry)
            revision = await setup_service.create_revision(
                _revision_body(workflow_pin, display_name="Concurrent customer"),
                actor.id,
            )
            await setup_service.validate_revision(revision.id, actor.id)
            actor_id = actor.id
            revision_id = revision.id

        async def activate() -> ActiveInstallation | InstallationError:
            async with sessions() as session:
                try:
                    return await InstallationService(session, registry=registry).activate_revision(
                        revision_id, actor_id
                    )
                except InstallationError as exc:
                    await session.rollback()
                    return exc

        results = await asyncio.gather(activate(), activate())
        successes = [item for item in results if isinstance(item, ActiveInstallation)]
        conflicts = [item for item in results if isinstance(item, InstallationError)]

        assert len(successes) == 1
        assert successes[0].fingerprint.authority_generation == 1
        assert len(conflicts) == 1
        assert conflicts[0].code == "INSTALLATION_CONFLICT"
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE audit_events, installation_state, "
                    "installation_manifest_validations, installation_manifest_revisions, "
                    "integration_settings, users CASCADE"
                )
            )
        await engine.dispose()
