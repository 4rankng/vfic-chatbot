"""PostgreSQL roundtrip proof for adapter-scoped persona assignments."""

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


async def test_adapter_persona_assignment_migration_roundtrip(
    integration_database: IntegrationDatabase,
) -> None:
    _alembic(integration_database, "downgrade", "0048_project_owned_knowledge_modes")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            columns = set(
                (
                    await connection.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'projects' AND column_name = 'default_persona_id'"
                        )
                    )
                ).all()
            )
            assert columns == {"default_persona_id"}
    finally:
        await engine.dispose()

    _alembic(integration_database, "upgrade", "0049_adapter_persona_assignments")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assignment_columns = set(
                (
                    await connection.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'adapter_persona_assignments'"
                        )
                    )
                ).all()
            )
            assert assignment_columns == {"provider", "persona_id", "created_at", "updated_at"}
            assert await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'projects' AND column_name = 'default_persona_id'"
                )
            ) is None
            assert await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'personas' AND column_name = 'project_id'"
                )
            ) is None
            index_def = await connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'personas' AND indexname = 'personas_one_active'"
                )
            )
            assert "WHERE is_active" in str(index_def)
            assert "project_id" not in str(index_def)
    finally:
        await engine.dispose()

    _alembic(integration_database, "downgrade", "0048_project_owned_knowledge_modes")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            restored = set(
                (
                    await connection.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'personas' AND column_name = 'project_id'"
                        )
                    )
                ).all()
            )
            assert restored == {"project_id"}
            assert await connection.scalar(
                text(
                    "SELECT to_regclass('public.adapter_persona_assignments')"
                )
            ) is None
    finally:
        await engine.dispose()

    _alembic(integration_database, "upgrade", "head")
