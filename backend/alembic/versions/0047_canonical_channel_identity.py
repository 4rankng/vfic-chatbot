"""canonical channel-account identity and provider-neutral message ids

Revision ID: 0047_canonical_channel_identity
Revises: 0046_standalone_knowledge_bases
Create Date: 2026-07-17

Phase 2 of the channel-neutral Facebook Messenger adapter. Makes channel
accounts and account-scoped identity canonical in persistence; preserves Zalo
fields as nullable compatibility aliases; backfills existing Zalo rows;
replaces the Zalo-only lead trigger with a contact-keyed one; adds
provider-neutral message ids and the durable inbound idempotency boundary.

DESIGN (approved 2026-07-17):
- Additive first, then backfill, then enforce NOT NULL in this same revision.
- Abort on ambiguity (orphan conversations, unresolved identities). Never
  auto-merge contacts or leads.
- No lead dedup: backfill ``leads.contact_id`` only; multiple leads may share
  a contact. A separately-reviewed cleanup rule may add uniqueness later.
- Zalo fields become nullable aliases for Messenger rows; Zalo rows retain
  their values.
- Downgrade is FAIL-CLOSED: refuses if any ``facebook_messenger`` rows exist
  (they cannot be made Zalo-compatible without fabricating ids). Raises an
  actionable error pointing at the disconnect/export procedure.

This migration is hand-written and approval-gated (AGENTS.md § Protected
operations). It does no network calls.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0047_canonical_channel_identity"
down_revision = "0046_standalone_knowledge_bases"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ── 1. Additive: channel_accounts registry ──────────────────────────────
    op.create_table(
        "channel_accounts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_key", sa.String(128), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("provider_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "account_key", name="uq_channel_accounts_provider_account_key"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="channel_account_status_values"),
        sa.CheckConstraint(
            "provider ~ '^[a-z0-9][a-z0-9._-]*$'", name="channel_account_provider_canonical"
        ),
    )
    op.create_index(
        "ix_channel_accounts_provider_status",
        "channel_accounts",
        ["provider", "status"],
    )
    # At most one ACTIVE facebook_messenger account in V1. Partial unique index.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_channel_accounts_one_active_facebook_messenger
            ON public.channel_accounts (provider)
            WHERE provider = 'facebook_messenger' AND status = 'ACTIVE'
        """
    )

    # ── 2. Additive: leads.contact_id ───────────────────────────────────────
    op.add_column(
        "leads",
        sa.Column("contact_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_leads_contact",
        "leads",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_leads_contact",
        "leads",
        ["contact_id"],
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )

    # ── 3. Additive: provider-neutral message ids + authority fence ─────────
    op.add_column(
        "messages",
        sa.Column("provider_message_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "outbound_outbox",
        sa.Column("provider_message_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "outbound_outbox",
        sa.Column("channel_account_generation", sa.BigInteger(), nullable=True),
    )

    # ── 4. Backfill: two stable Zalo channel accounts ───────────────────────
    op.execute(
        """
        INSERT INTO public.channel_accounts (provider, account_key, label, status, generation)
        VALUES
            ('zalo_bot', 'default:zalo_bot', 'Zalo Chatbot', 'ACTIVE', 1),
            ('zalo_oa',  'default:zalo_oa',  'Zalo Official Account', 'ACTIVE', 1)
        ON CONFLICT (provider, account_key) DO NOTHING
        """
    )

    # ── 5. Backfill: Contact + ContactChannelIdentity for each Zalo identity
    # Each distinct neutral (provider, account_key, external_id) becomes one
    # identity. External id strips the "oa:" storage prefix for OA.
    #
    # Determinism strategy: the contact id is derived deterministically from
    # the neutral triple via UUIDv5 (a hash-based UUID). This makes the whole
    # backfill idempotent across re-runs AND lets the identity INSERT look up
    # its contact by recomputing the same UUID — no fragile cross-statement
    # correlation needed. UUIDv5 namespace is a fixed seed constant.
    #
    # Step 5a: contacts. ON CONFLICT DO NOTHING makes this a true no-op on a
    # partial retry. gen_random_uuid() is deliberately avoided here because it
    # is non-deterministic and would create duplicate contacts on retry.
    op.execute(
        """
        WITH distinct_idents AS (
            SELECT DISTINCT
                CASE WHEN c.zalo_channel = 'oa' THEN 'zalo_oa' ELSE 'zalo_bot' END AS provider,
                CASE WHEN c.zalo_channel = 'oa' THEN 'default:zalo_oa' ELSE 'default:zalo_bot' END AS account_key,
                CASE
                    WHEN c.zalo_channel = 'oa' AND c.zalo_chat_id LIKE 'oa:%'
                        THEN substring(c.zalo_chat_id from 4)
                    ELSE c.zalo_chat_id
                END AS external_id
            FROM public.conversations c
        )
        INSERT INTO public.contacts (id, created_at, updated_at)
        SELECT
            uuid_generate_v5(
                '6f5c1d2e-3a4b-4c6d-9e8f-0a1b2c3d4e5f'::uuid,
                provider || ':' || account_key || ':' || external_id
            ),
            now(),
            now()
        FROM distinct_idents
        ON CONFLICT (id) DO NOTHING
        """
    )
    # Step 5b: identities. contact_id re-derived deterministically from the
    # same triple, so it matches exactly one contact from step 5a. The identity
    # id itself is non-deterministic (gen_random_uuid) — that's fine because
    # the unique key is the (provider, account_key, external_id) triple, not id.
    op.execute(
        """
        WITH distinct_idents AS (
            SELECT DISTINCT
                CASE WHEN c.zalo_channel = 'oa' THEN 'zalo_oa' ELSE 'zalo_bot' END AS provider,
                CASE WHEN c.zalo_channel = 'oa' THEN 'default:zalo_oa' ELSE 'default:zalo_bot' END AS account_key,
                CASE
                    WHEN c.zalo_channel = 'oa' AND c.zalo_chat_id LIKE 'oa:%'
                        THEN substring(c.zalo_chat_id from 4)
                    ELSE c.zalo_chat_id
                END AS external_id
            FROM public.conversations c
        )
        INSERT INTO public.contact_channel_identities
            (id, contact_id, provider, account_key, external_id, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            uuid_generate_v5(
                '6f5c1d2e-3a4b-4c6d-9e8f-0a1b2c3d4e5f'::uuid,
                provider || ':' || account_key || ':' || external_id
            ),
            provider, account_key, external_id, now(), now()
        FROM distinct_idents
        ON CONFLICT (provider, account_key, external_id) DO NOTHING
        """
    )

    # ── 6. Backfill: conversations.contact_id / channel_identity_id ─────────
    op.execute(
        """
        UPDATE public.conversations conv
        SET contact_id = ident.contact_id,
            channel_identity_id = ident.id
        FROM public.contact_channel_identities ident
        WHERE
            conv.contact_id IS NULL
            AND ident.provider = CASE WHEN conv.zalo_channel = 'oa' THEN 'zalo_oa' ELSE 'zalo_bot' END
            AND ident.account_key = CASE WHEN conv.zalo_channel = 'oa' THEN 'default:zalo_oa' ELSE 'default:zalo_bot' END
            AND ident.external_id = CASE
                WHEN conv.zalo_channel = 'oa' AND conv.zalo_chat_id LIKE 'oa:%'
                    THEN substring(conv.zalo_chat_id from 4)
                ELSE conv.zalo_chat_id
            END
        """
    )

    # ── 7. Abort on ambiguity: any unresolved conversation is a hard stop. ──
    # Never auto-merge or fabricate. The operator must resolve orphans first.
    op.execute(
        """
        DO $$
        DECLARE unresolved INTEGER;
        BEGIN
            SELECT COUNT(*) INTO unresolved
            FROM public.conversations
            WHERE contact_id IS NULL OR channel_identity_id IS NULL;
            IF unresolved > 0 THEN
                RAISE EXCEPTION
                    'ABORT 0047: % conversations could not be resolved to a channel identity; '
                    'resolve orphan/malformed rows before retrying', unresolved
                    USING ERRCODE = 'check_violation';
            END IF;
        END;
        $$
        """
    )

    # ── 8. Backfill: leads.contact_id through the conversation match ────────
    op.execute(
        """
        UPDATE public.leads l
        SET contact_id = c.contact_id
        FROM public.conversations c
        WHERE l.contact_id IS NULL
          AND l.zalo_id IS NOT NULL
          AND c.zalo_chat_id = l.zalo_id
          AND c.contact_id IS NOT NULL
        """
    )
    # Duplicate zalo_ids (multiple leads → one conversation/contact) are
    # intentionally retained; no uniqueness is added. Report only.
    op.execute(
        """
        DO $$
        DECLARE dup_leads INTEGER;
        BEGIN
            SELECT COUNT(*) INTO dup_leads
            FROM (
                SELECT contact_id FROM public.leads
                WHERE contact_id IS NOT NULL
                GROUP BY contact_id
                HAVING COUNT(*) > 1
            ) s;
            IF dup_leads > 0 THEN
                RAISE NOTICE
                    'NOTICE 0047: % contacts have multiple leads (retained; no dedup applied)', dup_leads;
            END IF;
        END;
        $$
        """
    )

    # ── 9. Backfill: provider-neutral message ids from Zalo aliases ─────────
    op.execute(
        """
        UPDATE public.messages
        SET provider_message_id = zalo_message_id
        WHERE provider_message_id IS NULL AND zalo_message_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE public.outbound_outbox
        SET provider_message_id = zalo_message_id
        WHERE provider_message_id IS NULL AND zalo_message_id IS NOT NULL
        """
    )

    # ── 10. Durable inbound idempotency: scoped partial unique index ────────
    op.create_index(
        "uq_messages_conv_provider_message",
        "messages",
        ["conversation_id", "provider_message_id"],
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )

    # ── 11. Replace the Zalo-only lead trigger with a contact-keyed one ─────
    op.execute("DROP TRIGGER IF EXISTS trg_conversation_lead_stub ON public.conversations")
    op.execute("DROP FUNCTION IF EXISTS public.ensure_conversation_lead()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.ensure_conversation_lead_by_contact()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.contact_id IS NULL THEN
                RETURN NEW;
            END IF;
            -- For Zalo rows, ON CONFLICT (zalo_id) dedups because zalo_chat_id
            -- is non-NULL and unique. For Messenger rows zalo_chat_id is NULL,
            -- so the ON CONFLICT target cannot fire — guard with NOT EXISTS on
            -- (contact_id, lead_stage='NEW') to avoid creating a fresh stub
            -- lead on every Messenger conversation INSERT for an existing
            -- contact. Multiple leads per contact are still allowed at other
            -- stages; only NEW-stage dedup is enforced (the stub phase).
            IF EXISTS (
                SELECT 1 FROM public.leads
                WHERE contact_id = NEW.contact_id AND lead_stage = 'NEW'
            ) THEN
                RETURN NEW;
            END IF;
            INSERT INTO public.leads (
                zalo_id, contact_id, lead_stage, assigned_recruiter_id, created_at, updated_at
            )
            VALUES (
                NEW.zalo_chat_id,
                NEW.contact_id,
                'NEW'::lead_stage,
                NEW.assigned_recruiter_id,
                now(),
                NEW.updated_at
            )
            ON CONFLICT (zalo_id) DO NOTHING;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_conversation_lead_by_contact
        AFTER INSERT ON public.conversations
        FOR EACH ROW
        EXECUTE FUNCTION public.ensure_conversation_lead_by_contact();
        """
    )

    # ── 12. Enforce NOT NULL on canonical identity (approved) ───────────────
    op.alter_column("conversations", "contact_id", nullable=False)
    op.alter_column("conversations", "channel_identity_id", nullable=False)

    # The check constraint conversation_identity_requires_contact is now
    # trivially satisfied (both NOT NULL) — leave it in place; it still guards
    # the composite FK invariant and is harmless.

    # ── 13. Make zalo_chat_id nullable (compatibility alias for Messenger) ──
    # Postgres UNIQUE allows multiple NULLs, so Messenger rows (zalo_chat_id
    # = NULL) coexist. Existing Zalo rows retain their values and uniqueness.
    # The UNIQUE constraint name from 0001 baseline is conversations_zalo_chat_id_key.
    op.alter_column("conversations", "zalo_chat_id", nullable=True)


# ---------------------------------------------------------------------------
# downgrade — FAIL CLOSED
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Refuse if any Messenger (or other non-Zalo) rows exist — they cannot be
    # made Zalo-compatible without fabricating ids, which would corrupt domain
    # meaning and block the whole point of the channel-neutral refactor.
    op.execute(
        """
        DO $$
        DECLARE fb_accounts INTEGER; fb_identities INTEGER; fb_convs INTEGER;
        BEGIN
            SELECT COUNT(*) INTO fb_accounts
            FROM public.channel_accounts WHERE provider <> ALL (ARRAY['zalo_bot','zalo_oa']);
            SELECT COUNT(*) INTO fb_identities
            FROM public.contact_channel_identities
            WHERE provider <> ALL (ARRAY['zalo_bot','zalo_oa']);
            SELECT COUNT(*) INTO fb_convs
            FROM public.conversations
            WHERE zalo_channel NOT IN ('bot','oa') OR zalo_channel IS NULL;
            IF fb_accounts + fb_identities + fb_convs > 0 THEN
                RAISE EXCEPTION
                    'REFUSE 0047 downgrade: non-Zalo rows present '
                    '(channel_accounts=%, identities=%, conversations=%). '
                    'Disconnect the Facebook Page and export/remove Messenger '
                    'data before downgrading; do not fabricate Zalo ids.',
                    fb_accounts, fb_identities, fb_convs
                    USING ERRCODE = 'check_violation';
            END IF;
        END;
        $$
        """
    )

    # Restore Zalo NOT NULL (all rows are Zalo-compatible here).
    op.alter_column("conversations", "zalo_chat_id", nullable=False)

    # Relax canonical identity back to nullable.
    op.alter_column("conversations", "channel_identity_id", nullable=True)
    op.alter_column("conversations", "contact_id", nullable=True)

    # Restore the original Zalo-only trigger.
    op.execute("DROP TRIGGER IF EXISTS trg_conversation_lead_by_contact ON public.conversations")
    op.execute("DROP FUNCTION IF EXISTS public.ensure_conversation_lead_by_contact()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.ensure_conversation_lead()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO public.leads (
                zalo_id, lead_stage, assigned_recruiter_id, created_at, updated_at
            )
            VALUES (
                NEW.zalo_chat_id,
                'NEW'::lead_stage,
                NEW.assigned_recruiter_id,
                now(),
                NEW.updated_at
            )
            ON CONFLICT (zalo_id) DO NOTHING;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_conversation_lead_stub
        AFTER INSERT ON public.conversations
        FOR EACH ROW
        EXECUTE FUNCTION public.ensure_conversation_lead();
        """
    )

    # Drop the durable inbound idempotency index.
    op.drop_index("uq_messages_conv_provider_message", table_name="messages")

    # Drop provider-neutral columns.
    op.drop_column("outbound_outbox", "channel_account_generation")
    op.drop_column("outbound_outbox", "provider_message_id")
    op.drop_column("messages", "provider_message_id")

    # Drop leads.contact_id (FK + index first).
    op.drop_index("ix_leads_contact", table_name="leads")
    op.drop_constraint("fk_leads_contact", "leads", type_="foreignkey")
    op.drop_column("leads", "contact_id")

    # Drop channel_accounts table.
    op.execute("DROP INDEX IF EXISTS public.uq_channel_accounts_one_active_facebook_messenger")
    op.drop_index("ix_channel_accounts_provider_status", table_name="channel_accounts")
    op.drop_table("channel_accounts")

    # NOTE: the backfilled contact_channel_identities / contacts / contact_id /
    # channel_identity_id values on existing Zalo conversations are INTENTIONALLY
    # LEFT IN PLACE. They remain valid for Zalo rows and do not affect the
    # restored Zalo-only runtime. Removing them would require a separate
    # reviewed cleanup and is not part of reverting this migration's schema
    # changes.
