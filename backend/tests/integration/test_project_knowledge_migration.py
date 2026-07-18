"""Production-shaped proof for the legacy LG Display RAG migration."""

from __future__ import annotations

import os
import subprocess
import uuid

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


async def test_single_legacy_rag_kb_is_linked_to_lg_display_without_content_cutover(
    integration_database: IntegrationDatabase,
) -> None:
    _alembic(integration_database, "downgrade", "0047_canonical_channel_identity")
    project_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO projects (id, slug, name, is_active) "
                    "VALUES (:pid, 'lg-display', 'LG Display', true)"
                ),
                {"pid": project_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_bases (id, slug, name, mode) "
                    "VALUES (:kid, 'legacy-lg-display', 'LG Display Knowledge', 'RAG')"
                ),
                {"kid": knowledge_base_id},
            )
    finally:
        await engine.dispose()

    _alembic(integration_database, "upgrade", "head")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(
                text("SELECT project_id FROM knowledge_bases WHERE id = :kid"),
                {"kid": knowledge_base_id},
            ) == project_id
            assert await connection.scalar(
                text("SELECT knowledge_base_id FROM projects WHERE id = :pid"),
                {"pid": project_id},
            ) == knowledge_base_id
            assert await connection.scalar(
                text("SELECT count(*) FROM knowledge_categories WHERE project_id = :pid"),
                {"pid": project_id},
            ) == 12
            assert await connection.scalar(
                text("SELECT category_authority_started FROM projects WHERE id = :pid"),
                {"pid": project_id},
            ) is False
            await connection.execute(
                text("DELETE FROM projects WHERE id = :pid"),
                {"pid": project_id},
            )
            assert await connection.scalar(
                text("SELECT count(*) FROM knowledge_bases WHERE id = :kid"),
                {"kid": knowledge_base_id},
            ) == 0
    finally:
        await engine.dispose()
