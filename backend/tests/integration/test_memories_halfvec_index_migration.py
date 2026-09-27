"""Memories retrieval must be served by the halfvec HNSW index (PERF-17).

Migration 0055 added a ``match_memories(query_embedding halfvec(3072), ...)``
overload, but ``CREATE OR REPLACE`` cannot replace a function whose argument
*type* differs, so the vector-typed signature from 0001 survived and the app
kept binding ``CAST(:emb AS vector)``. That binds to the exact-compute vector
overload, whose ``memories.embedding <=> <vector>`` expression the
``memories_embedding_halfvec_hnsw_idx`` HNSW index (0016) cannot serve — memory
recall brute-forced the table on every ``search_user_memory`` turn.

Three properties are pinned here against a live PostgreSQL + pgvector:

1. Head leaves exactly one ``match_memories`` signature and it takes
   ``halfvec`` — the vector overload is gone (0057).
2. The downgrades are symmetric: downgrading past 0056 restores the vector
   overload, and downgrading past 0055 removes the halfvec one, so a full
   downgrade returns the database to the 0001 state and re-upgrading lands
   back on halfvec. That walk runs on a database this module creates and
   drops, so no crash inside it can strand the session-shared one mid-chain.
3. Both statements ``DocumentRepository.match_memories`` issues bind their
   embedding as ``halfvec`` — the type the surviving function takes and the
   type the HNSW index is built on.
4. The planner picks the HNSW index for the chat-scoped table query and for
   the body of the installed ``match_memories``, with a vector-typed control
   query that provably cannot use it.

The statements are captured from the repository rather than copied, because
the whole defect was a *typed* argument inside a string literal: only
Postgres can say which overload wins, which type it derived, and which index
serves the result.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Protocol

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.services.retrieval.document_repository import DocumentRepository
from tests.integration.conftest import BACKEND_DIR, IntegrationDatabase
from tests.integration.test_migration_roundtrip_walk import (
    _roundtrip_database as _disposable_database,
)

pytestmark = pytest.mark.integration

INDEX_NAME = "memories_embedding_halfvec_hnsw_idx"
_ROW_COUNT = 2000
_EMBEDDING = "[" + ",".join(["0.0125"] * 3072) + "]"


class _AlembicTarget(Protocol):
    """The two URLs an alembic subprocess needs.

    Both the session-shared ``IntegrationDatabase`` and the throwaway database
    this module migrates are addressed through this, so a downgrade aimed at
    the wrong one is a wrong value, not a wrong type.
    """

    async_url: str
    sync_url: str


def _alembic(database: _AlembicTarget, command: str, target: str) -> None:
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
        timeout=300,
    )


async def _match_memories_arg_types(session: AsyncSession) -> list[str]:
    rows = await session.execute(
        text(
            "SELECT t.typname "
            "FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_type t ON t.oid = p.proargtypes[0] "
            "WHERE n.nspname = 'public' AND p.proname = 'match_memories' "
            "ORDER BY t.typname"
        )
    )
    return list(rows.scalars().all())


async def _alembic_revision(connection) -> str:
    """``alembic_version.version_num`` — where this database's schema actually is.

    Read from the table rather than from ``alembic current`` so a downgrade
    that never reached a later test (a killed worker, a crash mid-walk) is
    visible as a wrong value rather than as a cascade of unrelated failures.
    """
    rows = await connection.execute(text("SELECT version_num FROM alembic_version"))
    return ", ".join(rows.scalars().all())


class _RecordingSession:
    """Pass-through AsyncSession that keeps the statements it executed.

    ``match_memories`` builds its SQL inline, so the only way to explain the
    query the app really sends is to send it and keep it.
    """

    def __init__(self, inner: AsyncSession) -> None:
        self._inner = inner
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):  # noqa: ANN001, ANN202
        self.statements.append((str(statement.text), dict(params or {})))
        return await self._inner.execute(statement, params)

    def __getattr__(self, name):  # noqa: ANN001, ANN202
        return getattr(self._inner, name)


async def _seed_memories(connection) -> None:
    await connection.execute(
        text(
            "INSERT INTO memories (content, metadata, embedding) "
            "SELECT 'perf17 memory ' || g, "
            '       \'{"chat_id": "perf17-hnsw"}\'::jsonb, '
            "       (SELECT array_agg(random())::vector FROM generate_series(1, 3072)) "
            "FROM generate_series(1, :rows) AS g"
        ),
        {"rows": _ROW_COUNT},
    )
    await connection.execute(text("ANALYZE memories"))


async def _installed_function_body(connection) -> str:
    """``prosrc`` of the halfvec ``match_memories``, with its named arguments
    rewritten to positional parameters so it can be planned directly.

    ``EXPLAIN`` on a *call* to the function is useless here: the function
    carries ``SET search_path``, which stores a ``proconfig`` and blocks SQL
    function inlining, so the plan is a bare ``Function Scan on match_memories``
    with the access method hidden inside. Planning the installed body is the
    only way to see the index it depends on. A rename of any of the three
    parameters makes this fail loudly (unbound ``$n``), not silently.
    """
    body = await connection.scalar(
        text(
            "SELECT p.prosrc "
            "FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_type t ON t.oid = p.proargtypes[0] "
            "WHERE n.nspname = 'public' AND p.proname = 'match_memories' "
            "AND t.typname = 'halfvec'"
        )
    )
    assert body, "no halfvec match_memories function is installed"
    for name, position in (("query_embedding", 1), ("match_count", 2), ("filter", 3)):
        body = re.sub(rf"\b{name}\b", f"${position}", body)
    return body


def _sql_str(value: object) -> str:
    """Single-quoted SQL literal for a test-generated value."""
    return "'" + str(value).replace("'", "''") + "'"


_NAMED_PARAM_RE = re.compile(r"(?<!:):(\w+)")


def _dollar_param_sql(sql: str) -> str:
    """``:name`` placeholders -> ``$1..$n`` in order of first appearance."""
    order: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in order:
            order.append(name)
        return f"${order.index(name) + 1}"

    return _NAMED_PARAM_RE.sub(replace, sql)


async def _derived_parameter_types(connection, sql: str) -> list[str]:
    """Types Postgres itself infers for the query's parameters.

    ``match_memories(CAST($1 AS vector), ...)`` and
    ``match_memories(CAST($1 AS halfvec(3072)), ...)`` both RUN — vector casts
    to halfvec implicitly, so only the declared parameter type tells them
    apart, and the derived type is what function overload resolution keys on.
    """
    await connection.execute(text(f"PREPARE perf17_probe AS {_dollar_param_sql(sql)}"))
    try:
        rendered = await connection.scalar(
            text(
                "SELECT parameter_types::text FROM pg_prepared_statements "
                "WHERE name = 'perf17_probe'"
            )
        )
    finally:
        await connection.execute(text("DEALLOCATE perf17_probe"))
    assert rendered, "PREPARE did not report parameter types"
    return rendered.strip("{}").split(",")


async def _explain(connection, sql: str, params: dict) -> str:
    result = await connection.execute(text(f"EXPLAIN (FORMAT TEXT) {sql}"), params)
    return "\n".join(result.scalars().all())


def _assert_hnsw_plan(plan: str, described_as: str) -> None:
    assert INDEX_NAME in plan, (
        f"the planner did not choose {INDEX_NAME} for {described_as} — "
        f"memories retrieval is brute-forcing again.\nPlan:\n{plan}"
    )
    assert "Seq Scan on memories" not in plan, (
        f"{described_as} fell back to a sequential scan on memories.\nPlan:\n{plan}"
    )


async def test_head_leaves_only_the_halfvec_match_memories_overload(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            arg_types = await _match_memories_arg_types(connection)
    finally:
        await engine.dispose()

    assert arg_types == ["halfvec"], (
        f"head must expose exactly one match_memories signature, taking halfvec; found {arg_types}"
    )


async def test_the_vector_overload_is_restored_and_removed_symmetrically(
    integration_database: IntegrationDatabase,
) -> None:
    """0057 down -> vector overload returns; 0055 down -> halfvec overload goes.

    The walk runs against a throwaway database created and dropped by this
    test, never the session-shared one. Downgrading the shared database is
    only safe while the test is alive: a hard kill, a timeout, or an xdist
    worker crash between the two downgrades leaves every later integration
    test on a 0054 schema and reports it as a mystery missing-column error
    rather than as the crash that caused it.

    The isolation is asserted, not assumed: the shared database's migration
    revision and its ``match_memories`` overload set are re-read after every
    alembic step, so a walk pointed back at the shared URL fails here instead
    of quietly mutating it.
    """
    with _disposable_database() as scratch:
        _alembic(scratch, "upgrade", "head")
        scratch_engine = create_async_engine(scratch.async_url)
        shared_engine = create_async_engine(integration_database.async_url)
        try:

            async def scratch_state() -> tuple[str, list[str]]:
                async with scratch_engine.connect() as connection:
                    return (
                        await _alembic_revision(connection),
                        await _match_memories_arg_types(connection),
                    )

            async def shared_state() -> tuple[str, list[str]]:
                async with shared_engine.connect() as connection:
                    return (
                        await _alembic_revision(connection),
                        await _match_memories_arg_types(connection),
                    )

            head_revision, head_types = await scratch_state()
            assert head_types == ["halfvec"], (
                f"a freshly upgraded database must expose the head schema; found {head_types}"
            )
            assert scratch.sync_url != integration_database.sync_url, (
                "the throwaway database resolved to the session-shared one, so "
                "the walk below would downgrade the database every other "
                "integration test is using."
            )
            shared_before = await shared_state()
            assert shared_before == (head_revision, head_types), (
                "the shared integration database must sit at the head state this "
                f"test preserves, got {shared_before!r} against {head_revision!r}"
            )

            # Each step moves the throwaway database and nothing else.
            _alembic(scratch, "downgrade", "0056_project_external_api")
            assert (await scratch_state())[1] == ["halfvec", "vector"]
            assert await shared_state() == shared_before

            _alembic(scratch, "downgrade", "0054_channel_account_projects")
            assert (await scratch_state())[1] == ["vector"]
            assert await shared_state() == shared_before

            _alembic(scratch, "upgrade", "head")
            assert await scratch_state() == (head_revision, ["halfvec"])
            assert await shared_state() == shared_before
        finally:
            await scratch_engine.dispose()
            await shared_engine.dispose()


async def test_both_memories_retrieval_statements_use_the_hnsw_index(
    integration_database: IntegrationDatabase,
) -> None:
    """The app's chat-scoped query and the installed function body are both
    index-served, and both statements still return rows.

    Seeding happens on a connection that is never committed, so the 2000
    memory rows roll back with it and cannot contaminate the session-scoped
    database other integration tests share.
    """
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            await _seed_memories(connection)

            recorder = _RecordingSession(connection)
            repo = DocumentRepository(recorder)
            chat_scoped = await repo.match_memories(_EMBEDDING, 5, '{"chat_id": "perf17-hnsw"}')
            function_scoped = await repo.match_memories(_EMBEDDING, 5, "{}")
            assert len(recorder.statements) == 2
            (scoped_sql, scoped_params), (function_sql, function_params) = recorder.statements

            # Both statements must still run: the vector overload is gone, so
            # anything that fails to bind to the halfvec function raises here.
            assert len(chat_scoped) == 5
            assert len(function_scoped) == 5

            # The embedding argument must reach Postgres as halfvec: with the
            # vector overload gone a `vector` argument would still run (via the
            # implicit cast) but re-introduce the exact-compute plan.
            for sql in (scoped_sql, function_sql):
                derived = await _derived_parameter_types(connection, sql)
                assert derived[0] == "halfvec", (
                    f"the memories query binds its embedding as {derived[0]}, not halfvec."
                    f"\nSQL: {sql}"
                )

            _assert_hnsw_plan(
                await _explain(connection, scoped_sql, scoped_params),
                "the chat-scoped memories query",
            )

            # The function call itself explains as a Function Scan (see
            # _installed_function_body), so its access method is pinned by
            # planning the installed body with the same values. EXECUTE takes
            # no bind parameters, so they are inlined as literals — they are
            # values this test generated, not external input.
            await connection.execute(
                text(
                    "PREPARE perf17_match_memories(halfvec, integer, jsonb) AS "
                    + await _installed_function_body(connection)
                )
            )
            try:
                _assert_hnsw_plan(
                    await _explain(
                        connection,
                        "EXECUTE perf17_match_memories("
                        f"CAST({_sql_str(function_params['emb'])} AS halfvec(3072)), "
                        f"{int(function_params['k'])}, "
                        f"CAST({_sql_str(function_params['filter'])} AS jsonb))",
                        {},
                    ),
                    "the installed match_memories function body",
                )
            finally:
                await connection.execute(text("DEALLOCATE perf17_match_memories"))

            # Control: the same body with the halfvec cast stripped is a
            # vector-typed ORDER BY (0001's form) and nothing in this schema
            # can serve it, so the assertions above cannot pass vacuously —
            # they turn on the cast, not on the table being small.
            await connection.execute(
                text(
                    "PREPARE perf17_match_memories_control(vector, integer, jsonb) AS "
                    + re.sub(
                        r"::halfvec\(3072\)",
                        "",
                        await _installed_function_body(connection),
                    )
                )
            )
            try:
                control_plan = await _explain(
                    connection,
                    "EXECUTE perf17_match_memories_control("
                    f"CAST({_sql_str(function_params['emb'])} AS vector), "
                    f"{int(function_params['k'])}, "
                    f"CAST({_sql_str(function_params['filter'])} AS jsonb))",
                    {},
                )
                assert INDEX_NAME not in control_plan, (
                    "the vector-typed control query unexpectedly used the halfvec "
                    f"index, so the halfvec assertions prove nothing.\nPlan:\n{control_plan}"
                )
            finally:
                await connection.execute(text("DEALLOCATE perf17_match_memories_control"))
            await connection.rollback()
    finally:
        await engine.dispose()
