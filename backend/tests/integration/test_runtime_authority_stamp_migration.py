"""PostgreSQL upgrade/downgrade proof for runtime-authority stamp columns."""

from __future__ import annotations

import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import BACKEND_DIR, IntegrationDatabase

pytestmark = pytest.mark.integration


def _alembic(database: IntegrationDatabase, command: str, target: str) -> None:
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
        timeout=120,
    )


async def test_runtime_authority_stamp_migration_roundtrip(
    integration_database: IntegrationDatabase,
) -> None:
    _alembic(integration_database, "downgrade", "0044_generic_contact_case_kernel")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'outbound_outbox' AND column_name = 'runtime_fingerprint'"
                )
            ) is None
    finally:
        await engine.dispose()

    _alembic(integration_database, "upgrade", "0045_runtime_authority_stamps")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            for table in ("messages", "bot_runs", "outbound_outbox"):
                columns = set(
                    (
                        await connection.scalars(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name = :table AND column_name IN "
                                "('runtime_revision_id', 'authority_generation', 'runtime_fingerprint')"
                            ),
                            {"table": table},
                        )
                    ).all()
                )
                assert columns == {
                    "runtime_revision_id",
                    "authority_generation",
                    "runtime_fingerprint",
                }
            constraints = set(
                (
                    await connection.scalars(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE conrelid = 'outbound_outbox'::regclass"
                        )
                    )
                ).all()
            )
            assert {
                "ck_outbound_outbox_runtime_stamp_complete",
                "ck_outbound_outbox_origin_kind",
                "ck_outbound_outbox_fence_scope",
                "ck_outbound_outbox_authority_origin",
            } <= constraints
            stamp_check = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_outbound_outbox_runtime_stamp_complete'"
                )
            )
            origin_check = await connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_outbound_outbox_authority_origin'"
                )
            )
            assert "authority_generation IS NOT NULL" in str(stamp_check)
            assert "runtime_fingerprint IS NOT NULL" in str(stamp_check)
            assert "origin_kind IS NOT NULL" in str(origin_check)
            assert "fence_scope IS NOT NULL" in str(origin_check)

            # Alembic 0047 made contact_id + channel_identity_id NOT NULL on
            # conversations. Create a Contact + identity first, then the conversation.
            contact_id = await connection.scalar(
                text("INSERT INTO contacts (id) VALUES (gen_random_uuid()) RETURNING id")
            )
            identity_id = await connection.scalar(
                text(
                    "INSERT INTO contact_channel_identities "
                    "(id, contact_id, provider, account_key, external_id) "
                    "VALUES (gen_random_uuid(), :cid, 'zalo_bot', 'default:zalo_bot', 'runtime-stamp-proof') "
                    "RETURNING id"
                ),
                {"cid": contact_id},
            )
            conversation_id = await connection.scalar(
                text(
                    "INSERT INTO conversations (zalo_chat_id, zalo_channel, contact_id, channel_identity_id) "
                    "VALUES ('runtime-stamp-proof', 'bot', :cid, :iid) RETURNING id"
                ),
                {"cid": contact_id, "iid": identity_id},
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO messages "
                            "(conversation_id, sender, body, runtime_fingerprint) "
                            "VALUES (:conversation_id, 'BOT', 'partial stamp', :fingerprint)"
                        ),
                        {
                            "conversation_id": conversation_id,
                            "fingerprint": "a" * 64,
                        },
                    )
    finally:
        await engine.dispose()

    _alembic(integration_database, "downgrade", "0044_generic_contact_case_kernel")
    engine = create_async_engine(integration_database.async_url)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'messages' AND column_name = 'runtime_revision_id'"
                )
            ) is None
    finally:
        await engine.dispose()

    # This suite shares one disposable database. Restore the schema expected by
    # every subsequent integration test after proving the downgrade path.
    _alembic(integration_database, "upgrade", "head")
