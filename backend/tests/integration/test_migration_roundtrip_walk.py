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
    _current_revision,
    _database_url,
    _render,
)

pytestmark = pytest.mark.integration

_TIMEOUT = 300


def _alembic(database, command, target, *, rev="", check=True, extra=()):
    """Run one alembic step; on failure raise (check=True) or return the output."""
    env = os.environ.copy()
    env["APP_ENV"] = "development"
    env["DATABASE_URL"] = database.async_url
    env["DATABASE_URL_SYNC"] = database.sync_url
    result = subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), command, target, *extra],
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


def _applied_revision(database) -> str:
    """The revision id the database is stamped with, e.g. ``0057_drop_...``."""
    return _current_revision(database).split()[0]


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
# a migration fix lands. When a fix arrives, the walk fails with "no longer
# fails" until the entry is removed — a ratchet, not a skip. Keep this empty
# unless a new walk failure is deliberately parked with its error text below.
KNOWN_BROKEN_DOWNGRADES: set[str] = set()


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


def _chain_endpoints():
    """The single head and base revision of the chain."""
    script = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    heads = script.get_heads()
    assert heads and len(heads) == 1, "alembic must have exactly one head: " + str(heads)
    # `get_base()` returns a bare revision id on current alembic and a one-item
    # list on older ones; normalise so the assertion below is about the chain,
    # not about the alembic version.
    base = script.get_base()
    if not isinstance(base, str):
        assert len(base) == 1, "alembic must have exactly one base: " + str(base)
        base = base[0]
    return heads[0], base


# Both tests below live in the `integration` lane, so `pytest -m "not
# integration"` — the default gate — does not run them. A future reader
# assuming the gate covers this file is wrong: the gate must name this file
# explicitly, or the chain's reversibility is unenforced again.


def test_chain_reverses_to_base_and_reapplies():
    """The chain must survive head -> base -> head as a whole.

    Walking one revision at a time cannot catch a downgrade that is valid on its
    own but broken by the *next* downgrade in the reverse walk: that is how
    0006 removed the `PUBLISHED` enum label that 0005's downgrade filters on,
    so every individual `downgrade -1` succeeded while `downgrade base` could
    not complete.

    The target is the base revision rather than the CLI's literal ``base``,
    which means "one step *past* the base revision": 0001_baseline is a
    forward-only greenfield baseline whose downgrade raises on purpose, so the
    base revision is the deepest state a rollback can legally reach.
    """
    head, base = _chain_endpoints()
    with _roundtrip_database() as database:
        _alembic(database, "upgrade", "head", rev=head)
        assert _applied_revision(database) == head

        _alembic(database, "downgrade", base, rev=head)
        assert _applied_revision(database) == base

        # Re-applying from base is the half a rollback cannot recover from if
        # any downgrade left the schema in a state the next upgrade cannot read.
        _alembic(database, "upgrade", "head", rev=base)
        assert _applied_revision(database) == head


def test_reverse_chain_renders_offline():
    """`downgrade head:base --sql` must render, so a rollback can be reviewed first.

    In `--sql` mode alembic hands the migration a MockConnection, so any
    downgrade that inspects live data through `connection.scalar` dies with an
    AttributeError instead of producing a reviewable script.
    """
    head, base = _chain_endpoints()
    with _roundtrip_database() as database:
        _alembic(database, "upgrade", "head", rev=head)
        _alembic(
            database,
            "downgrade",
            f"{head}:{base}",
            rev=head,
            extra=("--sql",),
        )
