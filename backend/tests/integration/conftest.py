"""Isolated PostgreSQL fixtures for explicitly selected integration tests.

The fixture creates a uniquely named database, migrates it to Alembic head, and
drops it after the selected test session. It never skips: unavailable
infrastructure is a failing integration lane with an actionable error.
"""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
import warnings
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg
import pytest
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text as sa_text

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DATABASE_PREFIX = "vfic_integration_"
LOCAL_HTTP_HOSTS = {"127.0.0.1", "localhost", "testserver"}
LOOPBACK_DATABASE_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class IntegrationDatabase:
    name: str
    async_url: str
    sync_url: str


def _database_url(base: str, *, drivername: str, database: str) -> URL:
    return make_url(base).set(drivername=drivername, database=database)


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def assert_local_matching_database_urls(async_url: URL, sync_url: URL) -> None:
    async_endpoint = (
        async_url.username,
        async_url.password,
        async_url.host,
        async_url.port,
        async_url.database,
    )
    sync_endpoint = (
        sync_url.username,
        sync_url.password,
        sync_url.host,
        sync_url.port,
        sync_url.database,
    )
    if async_endpoint != sync_endpoint:
        raise RuntimeError("integration async/sync URLs must target the exact same endpoint")
    if sync_url.host not in LOOPBACK_DATABASE_HOSTS:
        raise RuntimeError("integration database host must be loopback-only")


def _run_alembic(database: IntegrationDatabase) -> None:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database.async_url,
            "DATABASE_URL_SYNC": database.sync_url,
        }
    )
    subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        timeout=120,
    )


@pytest.fixture(scope="session")
def integration_database() -> Iterator[IntegrationDatabase]:
    settings = get_settings()
    configured_async_url = make_url(settings.database_url)
    configured_sync_url = make_url(settings.database_url_sync)
    assert_local_matching_database_urls(configured_async_url, configured_sync_url)
    name = f"{TEST_DATABASE_PREFIX}{os.getpid()}_{uuid.uuid4().hex[:10]}"
    sync_base = _database_url(
        settings.database_url_sync,
        drivername="postgresql+psycopg",
        database="postgres",
    )
    admin_dsn = _render(sync_base.set(drivername="postgresql"))
    database = IntegrationDatabase(
        name=name,
        async_url=_render(
            _database_url(
                settings.database_url,
                drivername="postgresql+asyncpg",
                database=name,
            )
        ),
        sync_url=_render(
            _database_url(
                settings.database_url_sync,
                drivername="postgresql+psycopg",
                database=name,
            )
        ),
    )

    if not database.name.startswith(TEST_DATABASE_PREFIX):
        raise RuntimeError("refusing to create a database outside the integration-test prefix")

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(f'CREATE DATABASE "{database.name}"')
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "PostgreSQL integration lane requires the local pgvector dev service; "
            "start it with `docker compose -f docker-compose.dev.yml up -d postgres`."
        ) from exc

    original_database_url = os.environ.get("DATABASE_URL")
    original_database_url_sync = os.environ.get("DATABASE_URL_SYNC")
    try:
        _run_alembic(database)
        os.environ["DATABASE_URL"] = database.async_url
        os.environ["DATABASE_URL_SYNC"] = database.sync_url
        get_settings.cache_clear()
        yield database
    finally:
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url
        if original_database_url_sync is None:
            os.environ.pop("DATABASE_URL_SYNC", None)
        else:
            os.environ["DATABASE_URL_SYNC"] = original_database_url_sync
        get_settings.cache_clear()
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database.name,),
            )
            connection.execute(f'DROP DATABASE IF EXISTS "{database.name}"')


@pytest.fixture(autouse=True)
async def _bind_fastapi_database(integration_database: IntegrationDatabase):
    """Rebind the real ``get_db`` dependency to the disposable database."""
    from app.core import db as db_module

    original_engine = db_module.engine
    original_session_factory = db_module.async_session
    isolated_engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    db_module.engine = isolated_engine
    db_module.async_session = async_sessionmaker(
        isolated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        yield
    finally:
        db_module.engine = original_engine
        db_module.async_session = original_session_factory
        await isolated_engine.dispose()


@pytest.fixture
async def integration_session(
    integration_database: IntegrationDatabase,
) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with session_factory(bind=connection) as session:
                    yield session
            finally:
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()


# Migration tests downgrade the session-shared database. If an assertion fails
# before their own restore runs — or they simply forget one — every later test
# fails on missing columns, and the failure reports nothing about its real
# cause: one leaking test cascades into dozens of unrelated red tests. This
# guard puts head back after each schema-touching test and says which test left.
_MIGRATION_TEST_HINTS = ("migration", "roundtrip", "upgrade", "downgrade", "alembic")


def _current_revision(database: IntegrationDatabase) -> str:
    """One line of `alembic current`, e.g. ``0055_memories_match_halfvec (head)``."""
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database.async_url,
            "DATABASE_URL_SYNC": database.sync_url,
        }
    )
    result = subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), "current"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [
        line.strip()
        for line in (result.stdout + result.stderr).splitlines()
        if line.strip() and not line.startswith("INFO")
    ]
    return lines[0] if lines else ""


@pytest.fixture(autouse=True)
def _restore_head_after_schema_tests(
    request: pytest.FixtureRequest, integration_database: IntegrationDatabase
) -> Iterator[None]:
    """Restore alembic head after any test that may have migrated the database."""
    if not any(hint in request.node.nodeid for hint in _MIGRATION_TEST_HINTS):
        yield
        return
    yield
    revision = _current_revision(integration_database)
    if not revision or revision.endswith("(head)"):
        return
    # _run_alembic already runs `upgrade head`; it takes the database only.
    # Passing "upgrade", "head" here raised TypeError, so this safety net never
    # restored anything -- a test that left the shared database at an older
    # revision would surface as an unexplained schema error in a later test
    # rather than as a warning from the test that caused it.
    _run_alembic(integration_database)
    warnings.warn(
        f"{request.node.name} left the integration database at '{revision}'; "
        "head was restored by the conftest guard — the test itself must restore it.",
        stacklevel=1,
    )


@pytest.fixture(autouse=True)
async def _truncate_domain_tables_before_each_test(integration_database: IntegrationDatabase):
    """Clear domain tables before each integration test.

    The integration database is session-scoped (one DB per test session), so
    without per-test cleanup, rows from one test file contaminate the next.
    This matters acutely for migration tests: Alembic 0047's downgrade is
    fail-closed when non-Zalo rows exist, so a Messenger row left by an earlier
    test would block a later roundtrip test's downgrade. Truncating here keeps
    every test hermetic regardless of file ordering.

    Uses DELETE (not TRUNCATE) because TRUNCATE has no IF EXISTS clause and we
    want this to be safe at any revision a test might leave the DB in. Order
    respects FKs: children first.
    """
    admin_engine = create_async_engine(integration_database.async_url)
    try:
        async with admin_engine.begin() as conn:
            for table in (
                "messages",
                "outbound_outbox",
                "leads",
                "conversations",
                "contact_channel_identities",
                "contacts",
                "channel_accounts",
                "integration_settings",
            ):
                exists = await conn.scalar(
                    sa_text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
                )
                if exists is not None:
                    await conn.execute(sa_text(f"DELETE FROM {table}"))
    finally:
        await admin_engine.dispose()


@pytest.fixture(autouse=True)
def _block_external_http(monkeypatch: pytest.MonkeyPatch):
    original = httpx.AsyncClient.request
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def assert_local(address) -> None:
        if not isinstance(address, tuple) or not address:
            return
        host = str(address[0])
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError(f"external network is forbidden in integration tests: {host}")

    def guarded_connect(self, address):
        assert_local(address)
        return original_connect(self, address)

    def guarded_connect_ex(self, address):
        assert_local(address)
        return original_connect_ex(self, address)

    async def guarded(self, method, url, *args, **kwargs):
        target = httpx.URL(url)
        if target.host not in LOCAL_HTTP_HOSTS:
            raise AssertionError(f"external HTTP is forbidden in integration tests: {target.host}")
        return await original(self, method, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", guarded)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
