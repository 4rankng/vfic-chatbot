"""Alembic environment.

Uses the SYNC database url (psycopg) — Alembic is synchronous. The url is injected
from app settings so .env is the single source of truth.

The migration connection is bounded: lock_timeout fails fast when DDL queues
behind a long-running query (an unbounded ACCESS EXCLUSIVE wait hangs the deploy
with the old colour still serving), and statement_timeout stops a runaway
statement from stalling it silently. Both are env-overridable — set
ALEMBIC_LOCK_TIMEOUT_MS / ALEMBIC_STATEMENT_TIMEOUT_MS (0 disables) when a
migration legitimately needs a longer budget.

Note: the baseline migration is raw SQL (op.execute). target_metadata is wired for
future autogenerate support, but is not used to create the schema.
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.models.base import Base
import app.models  # noqa: F401  (register models on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

target_metadata = Base.metadata

LOCK_TIMEOUT_MS = os.environ.get("ALEMBIC_LOCK_TIMEOUT_MS", "5000")
STATEMENT_TIMEOUT_MS = os.environ.get("ALEMBIC_STATEMENT_TIMEOUT_MS", "900000")
PG_SESSION_OPTIONS = (
    f"-c lock_timeout={LOCK_TIMEOUT_MS} -c statement_timeout={STATEMENT_TIMEOUT_MS}"
)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"options": PG_SESSION_OPTIONS},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
