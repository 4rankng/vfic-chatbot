"""Exact empty-database downgrade/upgrade proof for migration 0042."""

from __future__ import annotations

import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import BACKEND_DIR, IntegrationDatabase

pytestmark = pytest.mark.integration


def _alembic(database: IntegrationDatabase, target: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database.async_url,
            "DATABASE_URL_SYNC": database.sync_url,
        }
    )
    subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), "upgrade", target]
        if target == "head"
        else [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), "downgrade", target],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        timeout=120,
    )


async def test_empty_installation_migration_downgrades_and_reapplies(
    integration_database: IntegrationDatabase,
):
    _alembic(integration_database, "0042_installation_revision_lifecycle")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT to_regclass('public.installation_setup_drafts')")
                )
                is None
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'installation_manifest_revisions' "
                        "AND column_name = 'authentication_policy'"
                    )
                )
                is None
            )
    finally:
        await engine.dispose()

    _alembic(integration_database, "head")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT to_regclass('public.installation_setup_drafts')")
                )
                == "installation_setup_drafts"
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM installation_setup_drafts")
                )
                == 0
            )
    finally:
        await engine.dispose()

    _alembic(integration_database, "0041_version_scope_typed_authority")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT to_regclass('public.installation_state')"))
                is None
            )
            assert (
                await connection.scalar(text("SELECT to_regclass('public.persona_versions')"))
                is None
            )
    finally:
        await engine.dispose()

    _alembic(integration_database, "head")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT to_regclass('public.installation_state')"))
                == "installation_state"
            )
            assert (
                await connection.scalar(text("SELECT to_regclass('public.persona_versions')"))
                == "persona_versions"
            )
    finally:
        await engine.dispose()
