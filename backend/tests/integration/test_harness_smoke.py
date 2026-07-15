"""Proof that the mandatory PostgreSQL integration lane is real and isolated."""

from __future__ import annotations

import socket

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import IntegrationDatabase, TEST_DATABASE_PREFIX

pytestmark = pytest.mark.integration
LEGACY_MIGRATION_SEEDS = {"worker_feature_catalog": 17}


async def test_migrated_pgvector_database_has_only_its_required_bootstrap_seed(
    integration_session,
    integration_database: IntegrationDatabase,
):
    database_name = await integration_session.scalar(text("SELECT current_database()"))
    vector_extension = await integration_session.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
    alembic_revision = await integration_session.scalar(
        text("SELECT version_num FROM alembic_version")
    )

    assert database_name == integration_database.name
    assert database_name.startswith(TEST_DATABASE_PREFIX)
    assert vector_extension
    assert alembic_revision

    worker_catalog_count = await integration_session.scalar(
        text("SELECT count(*) FROM worker_feature_catalog")
    )
    assert worker_catalog_count == LEGACY_MIGRATION_SEEDS["worker_feature_catalog"]


def test_external_socket_is_rejected_by_the_selected_integration_lane():
    with pytest.raises(AssertionError, match="external network is forbidden"):
        socket.socket().connect(("203.0.113.1", 443))


async def test_database_transaction_rollback_is_observable(
    integration_database: IntegrationDatabase,
):
    engine = create_async_engine(integration_database.async_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text("CREATE TABLE integration_rollback_probe (id integer)"))
        await connection.execute(text("INSERT INTO integration_rollback_probe VALUES (1)"))
        assert await connection.scalar(text("SELECT count(*) FROM integration_rollback_probe")) == 1
        await transaction.rollback()
        assert await connection.scalar(
            text("SELECT to_regclass('public.integration_rollback_probe')")
        ) is None
    await engine.dispose()


async def test_fastapi_database_dependency_is_rebound_to_the_disposable_database(
    integration_database: IntegrationDatabase,
):
    from app.core.db import get_db

    dependency = get_db()
    session = await anext(dependency)
    try:
        assert await session.scalar(text("SELECT current_database()")) == integration_database.name
    finally:
        await dependency.aclose()
