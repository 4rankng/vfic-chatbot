"""Every migration must survive upgrade, downgrade -1, and upgrade again."""

from __future__ import annotations

import os
import subprocess
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import get_settings
from tests.integration.conftest import (
    BACKEND_DIR,
    TEST_DATABASE_PREFIX,
    _database_url,
    _render,
)

pytestmark = pytest.mark.integration

_TIMEOUT = 300


def _alembic(database, command, target, *, rev="", check=True):
    """Run one alembic step; on failure raise (check=True) or return the output."""
    env = os.environ.copy()
    env["APP_ENV"] = "development"
    env["DATABASE_URL"] = database.async_url
    env["DATABASE_URL_SYNC"] = database.sync_url
    result = subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), command, target],
        cwd=str(BACKEND_DIR),
        env=env,
        check=False,
        timeout=_TIMEOUT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return None
    message = (
        f"alembic {command} {target} failed at revision {rev!r}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    if not check:
        return message
    raise AssertionError(message)


@contextmanager
def _roundtrip_database():
    settings = get_settings()
    name = TEST_DATABASE_PREFIX + "walk_" + uuid.uuid4().hex[:10]
    sync_base = _database_url(
        settings.database_url_sync,
        drivername="postgresql+psycopg",
        database="postgres",
    )
    admin_dsn = _render(sync_base.set(drivername="postgresql"))
    database = SimpleNamespace(
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
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute('CREATE DATABASE "' + name + '"')
    try:
        yield database
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute('DROP DATABASE IF EXISTS "' + name + '"')




# Downgrades proven broken by this walk live here, with the failing step, until
# the ops lane's migration fixes land. When a fix arrives, the walk fails with
# "no longer fails" until the entry is removed — a ratchet, not a skip.
#  - "0003": alembic downgrade 0003 -> 0002 raises
#    psycopg.errors.InvalidTableDefinition: cannot drop columns from view
KNOWN_BROKEN_DOWNGRADES: set[str] = {"0003"}


def test_every_migration_roundtrips_in_sequence():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert heads and len(heads) == 1, "alembic must have exactly one head: " + str(heads)
    walked = list(script.walk_revisions())
    revisions = [rev.revision for rev in reversed(walked)]
    assert len(revisions) >= 50, "the walk must cover the full chain"
    # A merge node has two parents, so "downgrade -1" has no single target.
    merge_revisions = {
        rev.revision for rev in walked if isinstance(rev.down_revision, tuple)
    }

    broken: dict[str, str] = {}
    with _roundtrip_database() as database:
        for index, rev in enumerate(revisions):
            _alembic(database, "upgrade", rev, rev=rev)
            if index == 0:
                continue  # the chain's base has nothing below it to downgrade to
            if rev in merge_revisions:
                continue
            result = _alembic(database, "downgrade", "-1", rev=rev, check=False)
            if result is not None:
                broken[rev] = result
                # Rebuild forward past the failed downgrade before continuing.
                _alembic(database, "upgrade", rev, rev=rev)
                continue
            _alembic(database, "upgrade", rev, rev=rev)
        _alembic(database, "upgrade", "head")

    unexpected = sorted(set(broken) - KNOWN_BROKEN_DOWNGRADES)
    healed = sorted(KNOWN_BROKEN_DOWNGRADES - set(broken))
    assert not unexpected, (
        "downgrades broke that are not on the known-broken list: " + str(unexpected)
    )
    assert not healed, (
        "downgrades on the known-broken list now pass — remove their entries: "
        + str(healed)
    )
