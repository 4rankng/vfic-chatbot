"""Schema and value-contract tests for immutable runtime authority stamps."""

from __future__ import annotations

import uuid
from pathlib import Path

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


def test_authority_stamp_migration_requires_complete_stamps_and_origin_specific_fences():
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0045_runtime_authority_stamps.py"
    ).read_text(encoding="utf-8")

    assert 'f"ck_{table}_runtime_stamp_complete"' in migration
    assert "runtime_revision_id IS NOT NULL AND authority_generation >= 0" in migration
    assert "origin_kind IN ('BOT','PROACTIVE','MANUAL')" in migration
    assert "fence_scope IN ('RUNTIME','CHANNEL')" in migration
    assert "ix_outbound_outbox_pending_runtime_authority" in migration
    assert "def downgrade" in migration
