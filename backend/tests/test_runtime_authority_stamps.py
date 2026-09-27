"""Schema and value-contract tests for immutable runtime authority stamps."""

from __future__ import annotations

import importlib.util
import io
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.conversation import BotRun, Message
from app.models.outbox import OutboundOutbox, OutboxFenceScope, OutboxOriginKind
from app.services.installation.authority import RuntimeAuthorityFingerprint


def _fingerprint() -> RuntimeAuthorityFingerprint:
    return RuntimeAuthorityFingerprint(
        authority_generation=7,
        revision_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        manifest_checksum="a" * 64,
        pack_contract_hash="b" * 64,
        persona_checksum="c" * 64,
        workflow_policy_checksum="d" * 64,
        provider_policy_checksum="e" * 64,
        authentication_policy_checksum="f" * 64,
        template_checksums={"template": "1" * 64},
        active_kb_vector=(("knowledge", "2" * 64),),
    )


def test_runtime_authority_stamp_is_complete_and_deterministic():
    fingerprint = _fingerprint()

    stamp = fingerprint.stamp()

    assert stamp.revision_id == fingerprint.revision_id
    assert stamp.authority_generation == 7
    assert stamp.fingerprint == fingerprint.checksum()
    assert len(stamp.fingerprint) == 64


def test_bot_and_outbound_models_carry_the_same_runtime_authority_columns():
    for model in (Message, BotRun, OutboundOutbox):
        assert {"runtime_revision_id", "authority_generation", "runtime_fingerprint"} <= set(
            model.__table__.columns.keys()
        )
    assert OutboxOriginKind.BOT.value == "BOT"
    assert OutboxFenceScope.RUNTIME.value == "RUNTIME"


STAMP_TABLES = ("messages", "bot_runs", "outbound_outbox")
MIGRATION = (
    Path(__file__).parents[1] / "alembic" / "versions" / "0045_runtime_authority_stamps.py"
)
_ADD_CONSTRAINT = re.compile(r"^ALTER TABLE (?P<table>\w+) ADD CONSTRAINT (?P<name>\w+) (?P<body>.*)$", re.S)
_ADD_COLUMN = re.compile(r"^ALTER TABLE (?P<table>\w+) ADD COLUMN (?P<name>\w+) (?P<body>.*)$", re.S)
_CREATE_INDEX = re.compile(
    r"^CREATE INDEX (?P<name>\w+) ON (?P<table>\w+) \((?P<columns>.*?)\)(?P<predicate>.*)$", re.S
)
_DROP = re.compile(r"DROP (?:CONSTRAINT|INDEX|COLUMN) (?P<name>\w+)")


def _rendered_statements(direction: str) -> list[str]:
    """Run the real `upgrade`/`downgrade` offline and return the SQL it emits.

    Alembic's offline mode compiles every `op.*` call against the PostgreSQL
    dialect without a server, so callers read the schema the migration actually
    produces instead of the source text that spells it.
    """
    spec = importlib.util.spec_from_file_location("_stamp_migration_0045", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": buffer},
    )
    with Operations.context(context):
        getattr(module, direction)()
    return [chunk.strip() for chunk in buffer.getvalue().split(";") if chunk.strip()]


def _constraints(statements: list[str]) -> dict[str, tuple[str, str]]:
    return {m["name"]: (m["table"], m["body"]) for m in map(_ADD_CONSTRAINT.match, statements) if m}


def _columns(statements: list[str]) -> dict[tuple[str, str], str]:
    return {(m["table"], m["name"]): m["body"] for m in map(_ADD_COLUMN.match, statements) if m}


def test_authority_stamp_migration_requires_complete_stamps_and_origin_specific_fences():
    """The upgrade really creates the stamp-completeness and origin/fence guards.

    This used to grep the migration file for its own string literals, so
    dropping or renaming a column in the DDL left the test green. Rendering the
    migration runs the production `upgrade()` and pins the schema it emits. The
    Postgres round-trip that proves the constraints actually reject a partial
    stamp lives in tests/integration/test_runtime_authority_stamp_migration.py.
    """
    statements = _rendered_statements("upgrade")
    constraints = _constraints(statements)
    columns = _columns(statements)

    for table in STAMP_TABLES:
        name = f"ck_{table}_runtime_stamp_complete"
        assert name in constraints, f"{name} was never created"
        constraint_table, body = constraints[name]
        assert constraint_table == table
        assert columns[(table, "runtime_revision_id")] == "UUID"
        assert columns[(table, "authority_generation")] == "BIGINT"
        assert columns[(table, "runtime_fingerprint")] == "VARCHAR(64)"
        # A stamp is all-or-nothing, non-negative, and a lowercase hex digest.
        assert "runtime_revision_id IS NULL AND authority_generation IS NULL" in body
        assert "runtime_fingerprint IS NULL" in body
        assert "authority_generation IS NOT NULL" in body
        assert "runtime_fingerprint IS NOT NULL" in body
        assert "authority_generation >= 0" in body
        assert "runtime_fingerprint ~ '^[0-9a-f]{64}$'" in body

    _, origin_kind = constraints["ck_outbound_outbox_origin_kind"]
    assert "origin_kind IS NULL OR origin_kind IN ('BOT','PROACTIVE','MANUAL')" in origin_kind
    _, fence_scope = constraints["ck_outbound_outbox_fence_scope"]
    assert "fence_scope IS NULL OR fence_scope IN ('RUNTIME','CHANNEL')" in fence_scope
    _, authority_origin = constraints["ck_outbound_outbox_authority_origin"]
    assert "origin_kind IS NULL AND fence_scope IS NULL" in authority_origin
    assert "origin_kind IS NOT NULL AND fence_scope IS NOT NULL" in authority_origin
    assert "origin_kind IN ('BOT','PROACTIVE') AND fence_scope = 'RUNTIME'" in authority_origin
    assert "origin_kind = 'MANUAL' AND fence_scope = 'CHANNEL'" in authority_origin

    indexes = [m for m in map(_CREATE_INDEX.match, statements) if m]
    pending = [m for m in indexes if m["name"] == "ix_outbound_outbox_pending_runtime_authority"]
    assert pending, "the pending-runtime-authority index was never created"
    assert pending[0]["table"] == "outbound_outbox"
    assert pending[0]["columns"] == "runtime_revision_id, authority_generation, created_at"
    assert "WHERE status = 'PENDING'" in pending[0]["predicate"]


def test_authority_stamp_migration_downgrade_reverses_the_whole_upgrade():
    """Every object the upgrade names is dropped again — a downgrade that
    forgets the index or a constraint would strand it on rollback."""
    upgrade = _rendered_statements("upgrade")
    dropped = {
        match["name"]
        for statement in _rendered_statements("downgrade")
        for match in map(_DROP.search, [statement])
        if match
    }
    created = (
        set(_constraints(upgrade))
        | {column for _table, column in _columns(upgrade)}
        | {m["name"] for m in map(_CREATE_INDEX.match, upgrade) if m}
    )

    assert created, "the upgrade created nothing to reverse"
    assert created <= dropped, f"downgrade leaves behind: {sorted(created - dropped)}"


async def test_stale_runtime_outbox_is_suppressed_before_provider_dispatch(monkeypatch):
    from app.services import outbox_service

    outbox = SimpleNamespace(
        status="PENDING",
        fence_scope="RUNTIME",
        runtime_revision_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        authority_generation=7,
        runtime_fingerprint="a" * 64,
    )
    db = SimpleNamespace(get=AsyncMock(return_value=outbox), commit=AsyncMock())
    acquire_lock = AsyncMock()
    current = AsyncMock(return_value=False)
    claim = AsyncMock(
        return_value=SimpleNamespace(outbox_id=11, message_id=22, channel="zalo_bot", payload={})
    )
    send = AsyncMock()

    monkeypatch.setattr(
        "app.services.installation.repository.InstallationRepository.acquire_runtime_dispatch_lock",
        acquire_lock,
    )
    monkeypatch.setattr(
        "app.services.installation.service.InstallationService.runtime_stamp_is_current",
        current,
    )
    monkeypatch.setattr(outbox_service, "claim_pending_outbox", claim)
    monkeypatch.setattr("app.services.zalo_sender.ZaloChannelSender.send_payload", send)

    result = await outbox_service.dispatch_outbox(db, outbox_id=11)

    assert result is not None
    assert result.suppressed is True
    # Phase 3: the legacy "suppressed" error_class was renamed to
    # "policy_suppressed" to align with the neutral ChannelErrorClass taxonomy.
    assert result.error_class == "policy_suppressed"
    acquire_lock.assert_awaited_once()
    current.assert_awaited_once()
    claim.assert_awaited_once_with(db, outbox_id=11)
    db.commit.assert_awaited_once()
    send.assert_not_awaited()


async def test_runtime_authority_is_rechecked_after_durable_claim(monkeypatch):
    from app.services import outbox_service

    outbox = SimpleNamespace(
        status="PENDING",
        fence_scope="RUNTIME",
        runtime_revision_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        authority_generation=7,
        runtime_fingerprint="a" * 64,
    )
    db = SimpleNamespace(get=AsyncMock(return_value=outbox), commit=AsyncMock())
    acquire_lock = AsyncMock()
    current = AsyncMock(side_effect=[True, False])
    claim = AsyncMock(
        return_value=SimpleNamespace(outbox_id=11, message_id=22, channel="zalo_bot", payload={})
    )
    provider_dispatch = AsyncMock()

    monkeypatch.setattr(
        "app.services.installation.repository.InstallationRepository.acquire_runtime_dispatch_lock",
        acquire_lock,
    )
    monkeypatch.setattr(
        "app.services.installation.service.InstallationService.runtime_stamp_is_current",
        current,
    )
    monkeypatch.setattr(outbox_service, "claim_pending_outbox", claim)
    monkeypatch.setattr(outbox_service, "_try_neutral_dispatch", provider_dispatch)

    result = await outbox_service.dispatch_outbox(db, outbox_id=11)

    assert result is not None
    assert result.suppressed is True
    assert result.error_class == "policy_suppressed"
    assert acquire_lock.await_count == 2
    assert current.await_count == 2
    claim.assert_awaited_once_with(db, outbox_id=11)
    db.commit.assert_awaited_once()
    provider_dispatch.assert_not_awaited()


async def test_current_runtime_keeps_post_claim_lock_through_provider_dispatch(monkeypatch):
    from app.services import outbox_service

    outbox = SimpleNamespace(
        status="PENDING",
        fence_scope="RUNTIME",
        runtime_revision_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        authority_generation=7,
        runtime_fingerprint="a" * 64,
    )
    candidate = SimpleNamespace(outbox_id=11, message_id=22, channel="zalo_bot", payload={})
    db = SimpleNamespace(get=AsyncMock(return_value=outbox), commit=AsyncMock())
    acquire_lock = AsyncMock()
    current = AsyncMock(side_effect=[True, True])
    claim = AsyncMock(return_value=candidate)
    cfg = SimpleNamespace()
    resolve_zalo = AsyncMock(return_value=cfg)
    provider_result = outbox_service.DispatchResult(
        outbox_id=11,
        message_id=22,
        ok=True,
        provider_message_id="provider-accepted",
    )
    provider_dispatch = AsyncMock(return_value=provider_result)

    monkeypatch.setattr(
        "app.services.installation.repository.InstallationRepository.acquire_runtime_dispatch_lock",
        acquire_lock,
    )
    monkeypatch.setattr(
        "app.services.installation.service.InstallationService.runtime_stamp_is_current",
        current,
    )
    monkeypatch.setattr(outbox_service, "claim_pending_outbox", claim)
    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        resolve_zalo,
    )
    monkeypatch.setattr(outbox_service, "_try_neutral_dispatch", provider_dispatch)

    result = await outbox_service.dispatch_outbox(db, outbox_id=11)

    assert result is provider_result
    assert acquire_lock.await_count == 2
    assert current.await_count == 2
    claim.assert_awaited_once_with(db, outbox_id=11)
    db.commit.assert_awaited_once()
    provider_dispatch.assert_awaited_once()


async def test_runtime_change_during_oa_refresh_is_policy_suppressed(monkeypatch):
    """A refresh commit must not turn lost authority into a retryable failure."""
    from app.services import outbox_service

    outbox = SimpleNamespace(
        status="PENDING",
        fence_scope="RUNTIME",
        runtime_revision_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        authority_generation=7,
        runtime_fingerprint="a" * 64,
    )
    candidate = SimpleNamespace(
        outbox_id=11,
        message_id=22,
        channel="zalo_oa",
        payload={"chat_id": "oa:user", "text": "hello"},
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=outbox),
        commit=AsyncMock(),
        # The OA channel resolves its account key from the message's conversation.
        execute=AsyncMock(return_value=SimpleNamespace(first=lambda: None)),
    )
    acquire_lock = AsyncMock()
    current = AsyncMock(side_effect=[True, True, False])

    async def provider_dispatch(
        _db, _candidate, _outbox, _cfg, _settings, refresh, *, account_key=None
    ):
        await refresh()
        raise AssertionError("refresh must suppress before provider retry")

    monkeypatch.setattr(
        "app.services.installation.repository.InstallationRepository.acquire_runtime_dispatch_lock",
        acquire_lock,
    )
    monkeypatch.setattr(
        "app.services.installation.service.InstallationService.runtime_stamp_is_current",
        current,
    )
    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.refresh_oa_access_token",
        AsyncMock(return_value="rotated-token"),
    )
    monkeypatch.setattr(
        outbox_service,
        "claim_pending_outbox",
        AsyncMock(return_value=candidate),
    )
    monkeypatch.setattr(outbox_service, "_try_neutral_dispatch", provider_dispatch)

    result = await outbox_service.dispatch_outbox(db, outbox_id=11)

    assert result is not None
    assert result.suppressed is True
    assert result.error_class == "policy_suppressed"
    assert "during OA credential refresh" in (result.error or "")
    assert acquire_lock.await_count == 3
    assert current.await_count == 3
