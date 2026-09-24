"""Phase 2: Alembic 0047 canonical channel identity migration round-trip.

Proves the hand-written migration (approval-gated per AGENTS.md):

1. Upgrade from 0046 with seeded Zalo conversations → backfills channel_accounts,
   contacts, contact_channel_identities, conversations.contact_id/channel_identity_id,
   leads.contact_id, and provider_message_id columns; enforces NOT NULL; replaces
   the lead trigger; makes zalo_chat_id nullable.
2. The contact-keyed trigger materializes a lead on a new conversation INSERT.
3. The durable inbound idempotency partial unique index enforces one row per
   (conversation_id, provider_message_id).
4. Downgrade to 0046 restores the Zalo-only trigger, relaxes NOT NULL, and
   drops the new table/columns — but only when no non-Zalo rows exist.
5. Downgrade FAILS CLOSED when a facebook_messenger row is present (cannot
   fabricate Zalo ids without corrupting domain meaning).

Requires the local pgvector integration database (see tests/integration/conftest.py).
"""

from __future__ import annotations

import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import BACKEND_DIR, IntegrationDatabase

pytestmark = pytest.mark.integration


def _alembic(database: IntegrationDatabase, command: str, target: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": database.async_url,
            "DATABASE_URL_SYNC": database.sync_url,
        }
    )
    return subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), command, target],
        cwd=BACKEND_DIR,
        env=env,
        timeout=120,
        capture_output=True,
        text=True,
    )


def _alembic_strict(database: IntegrationDatabase, command: str, target: str) -> None:
    result = _alembic(database, command, target)
    assert result.returncode == 0, (
        f"alembic {command} {target} failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


async def _seed_zalo_conversations(database: IntegrationDatabase) -> None:
    """Insert Zalo-shaped rows at the 0046 schema (before 0047 applies).

    Two Bot conversations + one OA conversation, each with a message carrying a
    zalo_message_id. Mirrors the production shape the backfill must resolve.
    Clears any leftover rows from a prior test first (the integration DB is
    session-scoped, so without cleanup the UNIQUE constraint on zalo_chat_id
    would collide across tests).
    """
    engine = create_async_engine(database.async_url)
    try:
        async with engine.begin() as conn:
            # Autouse fixture truncates before each test; no manual cleanup needed.
            await conn.execute(
                text(
                    "INSERT INTO conversations (id, zalo_chat_id, zalo_channel, mode, status, "
                    "needs_human, version, conversation_seq, unread_count, created_at, updated_at) "
                    "VALUES "
                    "  (gen_random_uuid(), 'bot-chat-1', 'bot', 'BOT', 'OPEN', false, 1, 1, 0, now(), now()),"
                    "  (gen_random_uuid(), 'bot-chat-2', 'bot', 'BOT', 'OPEN', false, 1, 1, 0, now(), now()),"
                    "  (gen_random_uuid(), 'oa:user-42', 'oa', 'BOT', 'OPEN', false, 1, 1, 0, now(), now())"
                )
            )
            # messages need a conversation_id; attach to each.
            await conn.execute(
                text(
                    "INSERT INTO messages (conversation_id, sender, body, delivery_status, "
                    "zalo_message_id, created_at) "
                    "SELECT id, 'WORKER', 'hi', 'SENT', 'zmid-' || zalo_chat_id, now() "
                    "FROM conversations"
                )
            )
    finally:
        await engine.dispose()


async def _count(database: IntegrationDatabase, sql: str) -> int:
    engine = create_async_engine(database.async_url)
    try:
        async with engine.connect() as conn:
            return int(await conn.scalar(text(sql)) or 0)
    finally:
        await engine.dispose()


async def _count(database: IntegrationDatabase, sql: str) -> int:
    engine = create_async_engine(database.async_url)
    try:
        async with engine.connect() as conn:
            return int(await conn.scalar(text(sql)) or 0)
    finally:
        await engine.dispose()


# ─── upgrade + backfill ─────────────────────────────────────────────────────


async def test_upgrade_backfills_zalo_channel_accounts(integration_database: IntegrationDatabase):
    # Start at 0046, seed, then upgrade to head (0047).
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    await _seed_zalo_conversations(integration_database)
    _alembic_strict(integration_database, "upgrade", "head")

    assert await _count(
        integration_database,
        "SELECT COUNT(*) FROM channel_accounts WHERE provider IN ('zalo_bot','zalo_oa')",
    ) == 2
    # Both Zalo accounts are ACTIVE with generation 1.
    assert await _count(
        integration_database,
        "SELECT COUNT(*) FROM channel_accounts WHERE status = 'ACTIVE' AND generation = 1",
    ) == 2


async def test_upgrade_backfills_identity_for_every_conversation(
    integration_database: IntegrationDatabase,
):
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    await _seed_zalo_conversations(integration_database)
    _alembic_strict(integration_database, "upgrade", "head")

    # 3 conversations → 2 bot identities + 1 oa identity = 3 distinct triples.
    assert await _count(integration_database, "SELECT COUNT(*) FROM contact_channel_identities") == 3
    assert await _count(integration_database, "SELECT COUNT(*) FROM contacts") == 3
    # Every conversation now has a canonical contact + identity (NOT NULL).
    assert await _count(
        integration_database,
        "SELECT COUNT(*) FROM conversations WHERE contact_id IS NULL "
        "OR channel_identity_id IS NULL",
    ) == 0


async def test_upgrade_strips_oa_storage_prefix(integration_database: IntegrationDatabase):
    """OA external ids are stored as 'oa:user-42' but the neutral identity strips
    the 'oa:' prefix so the external_id is the raw OA user id."""
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    await _seed_zalo_conversations(integration_database)
    _alembic_strict(integration_database, "upgrade", "head")

    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as conn:
            oa = await conn.execute(
                text(
                    "SELECT provider, account_key, external_id FROM contact_channel_identities "
                    "WHERE provider = 'zalo_oa'"
                )
            )
            row = oa.one()
            assert row.account_key == "default:zalo_oa"
            assert row.external_id == "user-42"  # prefix stripped
    finally:
        await engine.dispose()


async def test_upgrade_backfills_provider_message_ids(integration_database: IntegrationDatabase):
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    await _seed_zalo_conversations(integration_database)
    _alembic_strict(integration_database, "upgrade", "head")

    # Every seeded message had a zalo_message_id → provider_message_id backfilled.
    assert await _count(
        integration_database,
        "SELECT COUNT(*) FROM messages WHERE provider_message_id IS NULL",
    ) == 0
    # The values match.
    assert await _count(
        integration_database,
        "SELECT COUNT(*) FROM messages WHERE provider_message_id = zalo_message_id",
    ) == 3


async def test_upgrade_makes_zalo_chat_id_nullable(integration_database: IntegrationDatabase):
    """A Messenger conversation can now be inserted with zalo_chat_id = NULL."""
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    await _seed_zalo_conversations(integration_database)
    _alembic_strict(integration_database, "upgrade", "head")

    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as conn:
            # Insert a Messenger-style conversation: needs a contact + identity first.
            await conn.execute(
                text(
                    "INSERT INTO contacts (id) VALUES (gen_random_uuid()) RETURNING id"
                )
            )
            contact = (
                await conn.execute(text("SELECT id FROM contacts LIMIT 1"))
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO contact_channel_identities (id, contact_id, provider, account_key, external_id) "
                    "VALUES (gen_random_uuid(), :cid, 'facebook_messenger', 'page-1', 'PSID-1')"
                ),
                {"cid": contact},
            )
            identity = (
                await conn.execute(
                    text(
                        "SELECT id FROM contact_channel_identities "
                        "WHERE provider = 'facebook_messenger' LIMIT 1"
                    )
                )
            ).scalar()
            # zalo_chat_id = NULL, zalo_channel must still be NOT NULL — use a sentinel.
            await conn.execute(
                text(
                    "INSERT INTO conversations (zalo_chat_id, zalo_channel, contact_id, channel_identity_id) "
                    "VALUES (NULL, 'facebook_messenger', :cid, :iid)"
                ),
                {"cid": contact, "iid": identity},
            )
            assert await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM conversations WHERE zalo_chat_id IS NULL "
                    "AND zalo_channel = 'facebook_messenger'"
                )
            ) == 1
    finally:
        await engine.dispose()


# ─── trigger behavior ───────────────────────────────────────────────────────


async def test_contact_keyed_trigger_materializes_lead(integration_database: IntegrationDatabase):
    """Inserting a conversation post-migration creates/links a lead via contact_id."""
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    _alembic_strict(integration_database, "upgrade", "head")

    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as conn:
            contact = (
                await conn.execute(text("INSERT INTO contacts (id) VALUES (gen_random_uuid()) RETURNING id"))
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO contact_channel_identities (id, contact_id, provider, account_key, external_id) "
                    "VALUES (gen_random_uuid(), :cid, 'zalo_bot', 'default:zalo_bot', 'new-chat')"
                ),
                {"cid": contact},
            )
            identity = (
                await conn.execute(
                    text(
                        "SELECT id FROM contact_channel_identities WHERE external_id = 'new-chat'"
                    )
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO conversations (zalo_chat_id, zalo_channel, contact_id, channel_identity_id) "
                    "VALUES ('new-chat', 'bot', :cid, :iid)"
                ),
                {"cid": contact, "iid": identity},
            )
            # The contact-keyed trigger should have created a lead linked by contact_id.
            lead_contact = await conn.scalar(
                text(
                    "SELECT contact_id FROM leads WHERE zalo_id = 'new-chat'"
                )
            )
            assert lead_contact == contact
    finally:
        await engine.dispose()


# ─── durable idempotency ────────────────────────────────────────────────────


async def test_durable_inbound_idempotency_partial_unique_index(
    integration_database: IntegrationDatabase,
):
    """Two messages in the SAME conversation with the SAME provider_message_id
    must violate the partial unique index — the durable inbound dedup boundary."""
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    _alembic_strict(integration_database, "upgrade", "head")

    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as conn:
            contact = (
                await conn.execute(text("INSERT INTO contacts (id) VALUES (gen_random_uuid()) RETURNING id"))
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO contact_channel_identities (id, contact_id, provider, account_key, external_id) "
                    "VALUES (gen_random_uuid(), :cid, 'zalo_bot', 'default:zalo_bot', 'dup-chat')"
                ),
                {"cid": contact},
            )
            identity = (
                await conn.execute(
                    text("SELECT id FROM contact_channel_identities WHERE external_id = 'dup-chat'")
                )
            ).scalar()
            conv = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations (zalo_chat_id, zalo_channel, contact_id, channel_identity_id) "
                        "VALUES ('dup-chat', 'bot', :cid, :iid) RETURNING id"
                    ),
                    {"cid": contact, "iid": identity},
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO messages (conversation_id, sender, body, delivery_status, provider_message_id) "
                    "VALUES (:c, 'WORKER', 'a', 'SENT', 'mid-dup')"
                ),
                {"c": conv},
            )
            # Second insert with the same (conversation_id, provider_message_id) must fail.
            with pytest.raises(Exception):  # noqa: B017 - IntegrityError is DB-driver specific
                await conn.execute(
                    text(
                        "INSERT INTO messages (conversation_id, sender, body, delivery_status, provider_message_id) "
                        "VALUES (:c, 'WORKER', 'b', 'SENT', 'mid-dup')"
                    ),
                    {"c": conv},
                )
    finally:
        await engine.dispose()


# ─── downgrade ──────────────────────────────────────────────────────────────


async def test_downgrade_restores_zalo_only_state_when_no_messenger_rows(
    integration_database: IntegrationDatabase,
):
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    await _seed_zalo_conversations(integration_database)
    _alembic_strict(integration_database, "upgrade", "head")
    # Downgrade back to 0046 — should succeed because all rows are Zalo.
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")

    # channel_accounts table gone; leads.contact_id gone; provider_message_id gone.
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT to_regclass('public.channel_accounts')")) is None
            assert (
                await conn.scalar(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'leads' AND column_name = 'contact_id'"
                    )
                )
                is None
            )
            assert (
                await conn.scalar(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'messages' AND column_name = 'provider_message_id'"
                    )
                )
                is None
            )
            # zalo_chat_id is NOT NULL again.
            nullability = await conn.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'conversations' AND column_name = 'zalo_chat_id'"
                )
            )
            assert nullability == "NO"
            # The original Zalo-only trigger is back.
            trigger = await conn.scalar(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgname = 'trg_conversation_lead_stub'"
                )
            )
            assert trigger == "trg_conversation_lead_stub"
    finally:
        await engine.dispose()

    # Restore head: this session database is shared by every later test, and
    # leaving it at 0046 makes every test that expects the current schema fail.
    _alembic_strict(integration_database, "upgrade", "head")


async def test_downgrade_fails_closed_when_messenger_rows_present(
    integration_database: IntegrationDatabase,
):
    """Once a facebook_messenger row exists, downgrade must refuse rather than
    fabricate Zalo ids (the fail-closed contract from the approved design)."""
    _alembic_strict(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    _alembic_strict(integration_database, "upgrade", "head")

    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.begin() as conn:
            # Insert a facebook_messenger channel account.
            await conn.execute(
                text(
                    "INSERT INTO channel_accounts (provider, account_key, label, status, generation) "
                    "VALUES ('facebook_messenger', 'page-evil', 'Evil Page', 'ACTIVE', 1)"
                )
            )
    finally:
        await engine.dispose()

    # Downgrade must fail with a non-zero exit and an actionable error message.
    result = _alembic(integration_database, "downgrade", "0046_standalone_knowledge_bases")
    assert result.returncode != 0, (
        "downgrade must refuse when facebook_messenger rows are present; it succeeded"
    )
    combined = result.stdout + result.stderr
    assert "REFUSE 0047 downgrade" in combined or "non-Zalo rows present" in combined, (
        f"downgrade error must explain the refusal; got:\n{combined}"
    )

    # The refusal is expected, but it still ran the 0047..head downgrade chain
    # up to the point it refused: put the shared session database back at head
    # so the next test sees the current schema.
    _alembic_strict(integration_database, "upgrade", "head")
