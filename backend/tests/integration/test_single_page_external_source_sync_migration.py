from __future__ import annotations

import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import BACKEND_DIR, IntegrationDatabase

pytestmark = pytest.mark.integration


def _alembic(database: IntegrationDatabase, command: str, target: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database.async_url,
            "DATABASE_URL_SYNC": database.sync_url,
        }
    )
    subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), command, target],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        timeout=120,
    )


async def test_single_page_external_source_sync_migration_roundtrip(
    integration_database: IntegrationDatabase,
) -> None:
    _alembic(integration_database, "downgrade", "0052_external_source_sync_state")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(
                text("SELECT to_regclass('public.single_page_external_source_sync_state')")
            ) is None
        _alembic(integration_database, "upgrade", "head")
        async with engine.begin() as connection:
            assert await connection.scalar(
                text("SELECT to_regclass('public.single_page_external_source_sync_state')")
            ) == "single_page_external_source_sync_state"
            assert await connection.scalar(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'single_page_external_source_sync_state' "
                    "AND column_name = 'sheet_gid'"
                )
            ) == "bigint"
        _alembic(integration_database, "downgrade", "0052_external_source_sync_state")
        async with engine.begin() as connection:
            assert await connection.scalar(
                text("SELECT to_regclass('public.single_page_external_source_sync_state')")
            ) is None
    finally:
        _alembic(integration_database, "upgrade", "head")
        await engine.dispose()
