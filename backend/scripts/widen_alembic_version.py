#!/usr/bin/env python3
"""Idempotently widen ``alembic_version.version_num`` to ``VARCHAR(128)``.

Alembic creates ``alembic_version.version_num`` as ``VARCHAR(32)``, which is too
narrow for this project's descriptive revision IDs and aborts
``alembic upgrade head`` with ``StringDataRightTruncation`` on the version-row
UPDATE. Widening to ``VARCHAR(128)`` is metadata-only in Postgres (no table
rewrite, no long lock) and is safe to run on every deploy.

Run before ``alembic upgrade head`` (deploy Makefile + dev ``db`` target). The
baseline migration (0001) performs the same widening for fresh databases; this
script covers databases that already applied 0001 before the column was widened
(production, existing dev).

No-op when the table does not yet exist (fresh DB before its first migration) or
when the column is already wide enough — safe to invoke unconditionally.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from app.core.config import get_settings

_WIDEN_SQL = """
DO $$ BEGIN
    ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);
EXCEPTION WHEN undefined_table THEN NULL;
END $$;
"""


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url_sync)
    with engine.begin() as conn:
        conn.execute(text(_WIDEN_SQL))
    print("alembic_version.version_num is VARCHAR(128)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
