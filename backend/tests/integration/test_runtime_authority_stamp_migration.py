"""PostgreSQL upgrade/downgrade proof for runtime-authority stamp columns."""

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


async def test_runtime_authority_stamp_migration_roundtrip(
    integration_database: IntegrationDatabase,
) -> None:
    _alembic(integration_database, "downgrade", "0044_generic_contact_case_kernel")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'outbound_outbox' AND column_name = 'runtime_fingerprint'"
                )
            ) is None
    finally:
        await engine.dispose()

    _alembic(integration_database, "upgrade", "0045_runtime_authority_stamps")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            for table in ("messages", "bot_runs", "outbound_outbox"):
                columns = set(
                    (
                        await connection.scalars(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = :table AND column_name IN "
                                "('runtime_revision_id', 'authority_generation', 'runtime_fingerprint')"
                            ),
                            {"table": table},
                        )
                    ).all()
                )
                assert columns == {
                    "runtime_revision_id",
                    "authority_generation",
                    "runtime_fingerprint",
                }
            constraints = set(
                (
                    await connection.scalars(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conrelid = 'outbound_outbox'::regclass"
                        )
                    )
                ).all()
            )
            assert {
                "ck_outbound_outbox_runtime_stamp_complete",
                "ck_outbound_outbox_origin_kind",
                "ck_outbound_outbox_fence_scope",
                "ck_outbound_outbox_authority_origin",
            } <= constraints
    finally:
        await engine.dispose()

    _alembic(integration_database, "downgrade", "0044_generic_contact_case_kernel")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'messages' AND column_name = 'runtime_revision_id'"
                )
            ) is None
    finally:
        await engine.dispose()
