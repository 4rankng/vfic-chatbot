#!/usr/bin/env python3
"""Disposable FastAPI/PostgreSQL control plane for Playwright only.

Every command refuses databases without the ``_e2e`` suffix. Production code
does not import this module and no reset endpoint is mounted in the application.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg import sql
from redis import Redis
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ASYNC_URL = "postgresql+asyncpg://vfic:vfic@127.0.0.1:5443/vfic_e2e"
DEFAULT_SYNC_URL = "postgresql+psycopg://vfic:vfic@127.0.0.1:5443/vfic_e2e"
DEFAULT_ADMIN_EMAIL = "admin@example.org"
DEFAULT_ADMIN_PASSWORD = "Universal-E2E-Only-42!"
LOOPBACK_DATABASE_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_REDIS_URL = "redis://127.0.0.1:6382/15"
E2E_OWNER_TABLE = "_vfic_e2e_harness_owner"
E2E_RUN_ID = os.environ.get("VFIC_E2E_RUN_ID", "local")
E2E_OWNER_TOKEN = f"vfic-e2e-harness-v1:{E2E_RUN_ID}"
E2E_REDIS_OWNER_KEY = "_vfic_e2e_harness_owner"
NETWORK_GUARD_DIR = BACKEND_DIR / "tests" / "e2e_sitecustomize"


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _urls() -> tuple[URL, URL]:
    async_url = make_url(os.environ.get("VFIC_E2E_DATABASE_URL", DEFAULT_ASYNC_URL))
    sync_url = make_url(os.environ.get("VFIC_E2E_DATABASE_URL_SYNC", DEFAULT_SYNC_URL))
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
        raise RuntimeError("E2E async/sync database URLs must target the exact same endpoint")
    if sync_url.host not in LOOPBACK_DATABASE_HOSTS:
        raise RuntimeError("E2E database host must be loopback-only")
    if not (sync_url.database or "").endswith("_e2e"):
        raise RuntimeError("E2E database URLs must name the same database ending in `_e2e`")
    return async_url, sync_url


def _plain_psycopg(url: URL) -> str:
    return _render(url.set(drivername="postgresql"))


def _redis_url() -> str:
    value = os.environ.get("VFIC_E2E_REDIS_URL", DEFAULT_REDIS_URL)
    parsed = urlparse(value)
    if parsed.hostname not in LOOPBACK_DATABASE_HOSTS:
        raise RuntimeError("E2E Redis host must be loopback-only")
    try:
        database = int((parsed.path or "/0").lstrip("/") or "0")
    except ValueError as exc:
        raise RuntimeError("E2E Redis URL must contain a numeric database") from exc
    if database != 15:
        raise RuntimeError("E2E Redis must use the dedicated database 15")
    return value


def _redis(*, require_owned: bool) -> Redis:
    client = Redis.from_url(_redis_url(), decode_responses=True)
    owner = client.get(E2E_REDIS_OWNER_KEY)
    if require_owned and owner != E2E_OWNER_TOKEN:
        raise RuntimeError("refusing to reset Redis without the E2E ownership marker")
    if not require_owned and client.dbsize() and owner != E2E_OWNER_TOKEN:
        raise RuntimeError("refusing to claim a non-empty Redis database")
    return client


def _assert_database_owned(connection: psycopg.Connection) -> None:
    marker = connection.execute(
        "SELECT to_regclass(%s)", (f"public.{E2E_OWNER_TABLE}",)
    ).fetchone()
    if marker is None or marker[0] is None:
        raise RuntimeError("refusing destructive action on a database without E2E ownership")
    token = connection.execute(
        sql.SQL("SELECT owner_token FROM {} LIMIT 1").format(sql.Identifier(E2E_OWNER_TABLE))
    ).fetchone()
    if token is None or token[0] != E2E_OWNER_TOKEN:
        raise RuntimeError("refusing destructive action on a database with an unknown owner")


def _application_environment() -> dict[str, str]:
    async_url, sync_url = _urls()
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath = os.pathsep.join(
        value
        for value in (str(NETWORK_GUARD_DIR), str(BACKEND_DIR), existing_pythonpath)
        if value
    )
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": _render(async_url),
            "DATABASE_URL_SYNC": _render(sync_url),
            "REDIS_URL": _redis_url(),
            "PYTHONPATH": pythonpath,
            "CORS_ORIGINS": "http://127.0.0.1:4173,http://localhost:4173",
            "JWT_SECRET": "e2e-only-jwt-secret-at-least-32-characters",
            "INTEGRATION_SETTINGS_ENCRYPTION_KEY": "e2e-only-encryption-key-at-least-32-chars",
            "ZALO_BOT_TOKEN": "",
            "ZALO_BOT_WEBHOOK_SECRET": "",
            "ZALO_OA_ACCESS_TOKEN": "",
            "ZALO_OA_APP_ID": "",
            "ZALO_OA_SECRET_KEY": "",
            "ZALO_OA_REFRESH_TOKEN": "",
            "MINIMAX_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "GEMINI_API_KEY": "",
            "RESEND_API_KEY": "",
        }
    )
    return env


def prepare() -> None:
    _, sync_url = _urls()
    database_name = sync_url.database
    assert database_name is not None
    admin_url = sync_url.set(database="postgres")
    created = False
    with psycopg.connect(_plain_psycopg(admin_url), autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
        ).fetchone()
        if exists is None:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
            created = True

    try:
        with psycopg.connect(_plain_psycopg(sync_url), autocommit=True) as connection:
            if created:
                connection.execute(
                    sql.SQL("CREATE TABLE {} (owner_token text PRIMARY KEY)").format(
                        sql.Identifier(E2E_OWNER_TABLE)
                    )
                )
                connection.execute(
                    sql.SQL("INSERT INTO {} (owner_token) VALUES (%s)").format(
                        sql.Identifier(E2E_OWNER_TABLE)
                    ),
                    (E2E_OWNER_TOKEN,),
                )
            else:
                _assert_database_owned(connection)
        redis = _redis(require_owned=False)
        redis.set(E2E_REDIS_OWNER_KEY, E2E_OWNER_TOKEN)
        subprocess.run(
            [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=_application_environment(),
            check=True,
            timeout=120,
        )
    except Exception:
        if created:
            drop()
        raise


def reset(*, email: str, password: str) -> None:
    prepare()
    _, sync_url = _urls()
    from app.core.security import hash_password_sync

    admin_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    channel_identity_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    project_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    with psycopg.connect(_plain_psycopg(sync_url)) as connection:
        _assert_database_owned(connection)
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename NOT IN "
                "('alembic_version', %s)",
                (E2E_OWNER_TABLE,),
            ).fetchall()
        ]
        if tables:
            statement = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(table) for table in tables)
            )
            connection.execute(statement)
        connection.execute(
            "INSERT INTO users (id, email, password_hash, full_name, role, disabled, token_version) "
            "VALUES (%s, %s, %s, %s, 'admin', false, 0)",
            (
                admin_id,
                email.strip().lower(),
                hash_password_sync(password),
                "Universal E2E Admin",
            ),
        )
        connection.execute(
            "INSERT INTO contacts (id, display_name, primary_phone) VALUES (%s, %s, %s)",
            (contact_id, "E2E Candidate", "0900000000"),
        )
        connection.execute(
            "INSERT INTO contact_channel_identities "
            "(id, contact_id, provider, account_key, external_id) "
            "VALUES (%s, %s, 'zalo_oa', 'e2e-oa', 'e2e-candidate')",
            (channel_identity_id, contact_id),
        )
        connection.execute(
            "INSERT INTO conversations "
            "(id, zalo_chat_id, zalo_channel, mode, status, contact_id, "
            "channel_identity_id, last_inbound_at, last_outbound_at) "
            "VALUES (%s, 'oa:e2e-candidate', 'oa', 'BOT', 'OPEN', %s, %s, now(), now())",
            (conversation_id, contact_id, channel_identity_id),
        )
        connection.execute(
            "INSERT INTO messages "
            "(conversation_id, sender, body, delivery_status, zalo_message_id) "
            "VALUES (%s, 'WORKER', 'E2E inbound message', 'SENT', 'e2e-inbound'), "
            "(%s, 'BOT', 'E2E bot reply', 'SENT', 'e2e-outbound')",
            (conversation_id, conversation_id),
        )
        connection.execute(
            "INSERT INTO knowledge_bases (id, name, slug, mode) "
            "VALUES (%s, 'E2E Project', 'e2e-project', 'RAG')",
            (knowledge_base_id,),
        )
        connection.execute(
            "INSERT INTO projects (id, slug, name, is_active, knowledge_base_id) "
            "VALUES (%s, 'e2e-project', 'E2E Project', true, %s)",
            (project_id, knowledge_base_id),
        )
        # One terminal bot run with a schema-valid v2 decision trace so the
        # bot-runs list and its trace detail have a row to render.
        decision_trace = (
            '{"version": 2, "events": [{"seq": 1, "kind": "model_turn", "turn": 1, '
            '"phase": "final", "provider": "minimax", "model": "minimax-m2", '
            '"reasoning_status": "not_returned", "tool_names": []}], "truncated": false}'
        )
        connection.execute(
            "INSERT INTO bot_runs (conversation_id, started_at, ended_at, "
            "version_at_start, proposed_reply, outcome, decision_trace) "
            "VALUES (%s, now(), now(), 1, 'E2E bot reply', 'SENT', %s::jsonb)",
            (conversation_id, decision_trace),
        )
        connection.commit()
    redis = _redis(require_owned=True)
    redis.flushdb()
    redis.set(E2E_REDIS_OWNER_KEY, E2E_OWNER_TOKEN)


def drop() -> None:
    _, sync_url = _urls()
    database_name = sync_url.database
    assert database_name is not None and database_name.endswith("_e2e")
    admin_url = sync_url.set(database="postgres")
    with psycopg.connect(_plain_psycopg(sync_url), autocommit=True) as owned_connection:
        _assert_database_owned(owned_connection)
    with psycopg.connect(_plain_psycopg(admin_url), autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database_name,),
        )
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
        )
    redis = _redis(require_owned=True)
    redis.flushdb()


def serve(*, port: int) -> None:
    reset(email=DEFAULT_ADMIN_EMAIL, password=DEFAULT_ADMIN_PASSWORD)
    env = _application_environment()
    os.chdir(BACKEND_DIR)
    os.execve(
        str(BACKEND_DIR / ".venv" / "bin" / "uvicorn"),
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Control the disposable E2E database/server")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    subparsers.add_parser("drop")
    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("--email", default=DEFAULT_ADMIN_EMAIL)
    reset_parser.add_argument("--password", default=DEFAULT_ADMIN_PASSWORD)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.command == "prepare":
        prepare()
    elif args.command == "drop":
        drop()
    elif args.command == "reset":
        reset(email=args.email, password=args.password)
    elif args.command == "serve":
        serve(port=args.port)
    else:  # pragma: no cover - argparse enforces the command set
        return 2
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND_DIR))
    raise SystemExit(main())
