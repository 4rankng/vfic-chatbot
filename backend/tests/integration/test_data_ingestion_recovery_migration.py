"""Upgrade/default/downgrade proof for category ingestion recovery state."""

from __future__ import annotations

import os
import subprocess

import psycopg
import pytest
from sqlalchemy.engine import make_url

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
        capture_output=True,
        text=True,
    )


def _columns(database: IntegrationDatabase, table: str) -> set[str]:
    connection_url = make_url(database.sync_url).set(drivername="postgresql")
    with psycopg.connect(connection_url.render_as_string(hide_password=False)) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table,),
            )
        }


async def test_ingestion_recovery_migration_roundtrip_and_defaults(
    integration_database: IntegrationDatabase,
) -> None:
    revision_columns = {
        "processing_token",
        "processing_started_at",
        "lease_expires_at",
        "attempt_count",
        "failure_code",
        "quality_result",
    }
    project_columns = {"category_cutover_snapshot", "category_cutover_at"}

    assert revision_columns <= _columns(
        integration_database,
        "knowledge_category_revisions",
    )
    assert project_columns <= _columns(integration_database, "projects")

    try:
        _alembic(
            integration_database,
            "downgrade",
            "0049_adapter_persona_assignments",
        )
        assert revision_columns.isdisjoint(
            _columns(integration_database, "knowledge_category_revisions")
        )
        assert project_columns.isdisjoint(_columns(integration_database, "projects"))
    finally:
        _alembic(integration_database, "upgrade", "head")

    connection_url = make_url(integration_database.sync_url).set(drivername="postgresql")
    with psycopg.connect(connection_url.render_as_string(hide_password=False)) as connection:
        defaults = dict(
            connection.execute(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'knowledge_category_revisions' "
                "AND column_name IN ('attempt_count', 'quality_result')"
            ).fetchall()
        )
    assert defaults["attempt_count"] == "0"
    assert defaults["quality_result"] == "'{}'::jsonb"
