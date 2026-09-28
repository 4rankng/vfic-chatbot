"""Reconcile-sweep SQL for conversations.

The recovery sweep's query machinery, split out of the CRM inbox reads in
``repository.py``. It is a mixin on :class:`ConversationRepository` so the
sweep's single entry points (``find_reconcile_candidates``,
``latest_inbound_never_given_a_turn``) stay reachable as repository methods —
they share the repository's session and nothing else.

The masked-inbound fragment below is defined ONCE here and interpolated into
both queries: the per-conversation re-check the tick runs before it acts on a
candidate has to prove exactly what the batch scan selected, so a second copy
of this SQL is a correctness bug, not a refactor.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, text

from app.models.conversation import Conversation

# The outcome statuses whose own outbound command can prove that they answered an
# OLDER inbound than the newest candidate message (see ``_MASKED_INBOUND_SQL``).
# PENDING/SENDING/FAILED are deliberately absent: they keep their existing
# recovery paths (stale placeholder, delivery-failure retry) unchanged, and the
# sweep never selects them for this branch. Shared with the reconcile tick, which
# re-verifies the proof before it acts on such a candidate.
SUPERSEDED_OUTCOME_STATUSES = ("SENT", "DELIVERED", "READ", "SUPPRESSED", "SEND_UNKNOWN")

_SUPERSEDED_STATUS_LITERALS = ", ".join(f"'{status}'" for status in SUPERSEDED_OUTCOME_STATUSES)

# ── The durable link between a BOT outcome row and the inbound it answered ──
#
# A turn records the inbound it answered as the ``quote_message_id`` of the
# outbound command it writes together with its outcome
# (``graph/runner._build_outbox_payload`` from ``BotRunState.reply_to_message_id``,
# persisted by ``record_bot_outcome`` into ``outbound_outbox``). That command is
# the only durable per-message link: the BOT message row itself carries no reply
# id, and ``bot_runs.version_at_start`` is a conversation version (also bumped by
# recruiter actions), so it cannot identify an inbound.
#
# The fragment below matches the production shape this sweep exists for: an
# inbound that arrived while a turn held the per-chat mutex is persisted and then
# dropped (``services/webhook.py`` returns ``{"status": "locked"}`` without
# enqueuing a job), and the turn — enqueued before the drop, picking up after it —
# writes its own outcome row *after* the dropped message. That outcome answers an
# OLDER inbound, so its command quotes a different provider id than the newest
# candidate message: the dropped inbound provably never got a turn, while the
# outcome row would otherwise mask the conversation from this sweep forever. The
# worker's newest-inbound hand-off is the fast path; this is the durable net
# behind it.
#
# Loop-safety: the newest message must BE that completed outcome row, and the
# command must prove it answered a *different* inbound than the newest candidate
# message. An outcome that answered the newest candidate message — including one
# that answered it with a deliberate SUPPRESSED silence — quotes that message and
# is excluded, so a suppressed turn is never re-answered. A row written without a
# command (a pre-send suppression: lost claim, silent terminal, LLM throttle) has
# no link at all and is left to the hand-off rather than guessed at.
_MASKED_INBOUND_SQL = f"""
    EXISTS (
        SELECT 1
          FROM messages bm
          JOIN outbound_outbox bo ON bo.message_id = bm.id
         WHERE bm.conversation_id = c.id
           AND bm.sender = 'BOT'
           AND bm.id = (
               SELECT n.id FROM messages n
                WHERE n.conversation_id = c.id
                ORDER BY n.created_at DESC, n.id DESC
                LIMIT 1
           )
           AND bm.delivery_status IN ({_SUPERSEDED_STATUS_LITERALS})
           AND COALESCE(bo.payload ->> 'quote_message_id', '') <> ''
           AND COALESCE(bo.payload ->> 'quote_message_id', '') <> COALESCE(
               (
                   SELECT COALESCE(w.provider_message_id, w.zalo_message_id)
                     FROM messages w
                    WHERE w.conversation_id = c.id
                      AND w.sender = 'WORKER'
                    ORDER BY w.created_at DESC, w.id DESC
                    LIMIT 1
               ),
               ''
           )
           AND EXISTS (
               SELECT 1
                 FROM messages iw
                WHERE iw.conversation_id = c.id
                  AND iw.sender = 'WORKER'
                  -- The same newest candidate message the quote was compared
                  -- against: the grace/max-age window and the recruiter guard
                  -- apply to it, not to some older message.
                  AND iw.id = (
                      SELECT w2.id FROM messages w2
                       WHERE w2.conversation_id = c.id
                         AND w2.sender = 'WORKER'
                       ORDER BY w2.created_at DESC, w2.id DESC
                       LIMIT 1
                  )
                  AND iw.created_at < :now_minus_grace
                  AND iw.created_at > :now_minus_max_age
                  AND NOT EXISTS (
                      SELECT 1 FROM messages hr
                       WHERE hr.conversation_id = c.id
                         AND hr.sender = 'RECRUITER'
                         AND hr.id > iw.id
                         AND hr.delivery_status IN ('SENT', 'DELIVERED', 'READ')
                  )
           )
    )
"""


class ReconcileQueriesMixin:
    """The reconcile sweep's candidate scan and its per-conversation re-check.

    Mixed into :class:`~app.services.conversation.repository.ConversationRepository`
    so the sweep keeps one entry-point type; it needs only ``self.db``.
    """

    async def find_reconcile_candidates(
        self,
        *,
        now: datetime,
        grace_seconds: int,
        max_age_seconds: int,
        limit: int,
        stale_lock_seconds: int = 60,
    ) -> list[Conversation]:
        """Conversations whose newest message is unanswered or recoverable BOT failure.

        Loop-free predicate: a completed turn (sent or suppressed) leaves a
        ``BOT/SENT`` or ``BOT/SUPPRESSED`` row as the newest message, so it is
        excluded.  Only ``WORKER`` (never processed), ``BOT/PENDING`` (turn
        started but never completed), ``BOT/SENDING`` (claimed but never confirmed
        — a worker crash after the POST; reconciled as sent-but-unconfirmed), or
        ``BOT/FAILED`` (Zalo rejected delivery) qualify, except for the known
        permanent OA recipient rejection.

        A ``BOT/FAILED`` row that already carries a provider message id is also
        excluded: it delivered at least its first bubble (REL-01 — a chunked
        answer whose later bubble failed), so it is a partial delivery, not a
        lost turn, and re-answering would duplicate the bubble the candidate
        already saw. ``BOT/PENDING``/``BOT/SENDING`` rows are never excluded this
        way — a provider id on those is a receipt that a live send is resolving.

        One more shape qualifies, and it is the one the loop-free rule would
        otherwise hide for good: the newest message is a completed ``BOT`` outcome
        whose durable outbound command quotes a DIFFERENT inbound than the newest
        candidate message (``_MASKED_INBOUND_SQL``).  That outcome answered an
        older inbound, so the newest candidate message arrived while its turn held
        the per-chat mutex, was dropped by the ingress, and never got a turn.

        A conversation whose per-chat lock is still live but whose owner heartbeat
        is older than ``stale_lock_seconds`` (the RQ job-timeout horizon) is also
        included, so a crashed worker's lock can be force-broken and the turn
        recovered instead of waiting the full ``bot_lock_ttl``.

        SEMI_AUTO 30-min-inactivity is NOT in SQL — it is re-checked in Python
        inside the tick (depends on ``taken_over_at``/``updated_at``).
        """
        now_minus_grace = now - timedelta(seconds=grace_seconds)
        now_minus_max_age = now - timedelta(seconds=max_age_seconds)
        now_minus_stale_lock = now - timedelta(seconds=stale_lock_seconds)
        # NOTE: use select(Conversation).from_statement(text(...)) instead of
        # db.scalars(text(...)) — the latter returns only the first column (c.id
        # as a raw asyncpg UUID) rather than a Conversation ORM instance, causing
        # AttributeError downstream in reconcile_worker when it accesses conv.id.
        stmt = select(Conversation).from_statement(
            text(
                f"""
                    SELECT c.*
                      FROM conversations c
                     WHERE c.mode IN ('BOT', 'SEMI_AUTO')
                       AND (
                           c.bot_locked_until IS NULL
                           OR c.bot_locked_until < :now
                           OR (
                               c.bot_locked_until IS NOT NULL
                               AND c.bot_lock_heartbeat_at IS NOT NULL
                               AND c.bot_lock_heartbeat_at < :stale_cutoff
                           )
                       )
                       AND c.status = 'OPEN'
                       AND (c.followup_opted_out = FALSE OR c.followup_opted_out IS NULL)
                       AND (
                           EXISTS (
                               SELECT 1 FROM messages m
                                WHERE m.conversation_id = c.id
                                  AND m.id = (
                                      SELECT m2.id FROM messages m2
                                       WHERE m2.conversation_id = c.id
                                       ORDER BY m2.created_at DESC, m2.id DESC
                                       LIMIT 1
                                  )
                                  AND (
                                      m.sender = 'WORKER'
                                      OR (
                                          m.sender = 'BOT'
                                          AND m.delivery_status IN ('PENDING', 'SENDING', 'FAILED')
                                          AND NOT (
                                              m.delivery_status = 'FAILED'
                                              AND c.zalo_channel = 'oa'
                                              AND lower(COALESCE(m.external_error, ''))
                                                  LIKE '%user_id is invalid%'
                                          )
                                          -- REL-01: a FAILED answer that already
                                          -- carries a provider message id delivered
                                          -- at least its first bubble (a chunked
                                          -- send whose later bubble failed), so it
                                          -- is NOT a lost turn — re-answering would
                                          -- duplicate the bubble the candidate saw.
                                          AND NOT (
                                              m.delivery_status = 'FAILED'
                                              AND COALESCE(
                                                  NULLIF(m.provider_message_id, ''),
                                                  NULLIF(m.zalo_message_id, '')
                                              ) IS NOT NULL
                                          )
                                      )
                                  )
                                  AND m.created_at < :now_minus_grace
                                  AND m.created_at > :now_minus_max_age
                           )
                           OR ({_MASKED_INBOUND_SQL})
                       )
                     ORDER BY c.last_inbound_at DESC NULLS LAST
                     LIMIT :limit
                    """
            )
        )
        rows = (
            await self.db.scalars(
                stmt,
                {
                    "now": now,
                    "now_minus_grace": now_minus_grace,
                    "now_minus_max_age": now_minus_max_age,
                    "stale_cutoff": now_minus_stale_lock,
                    "limit": limit,
                },
            )
        ).all()
        return list(rows)

    async def latest_inbound_never_given_a_turn(
        self,
        conv: Conversation,
        *,
        now: datetime,
        grace_seconds: int,
        max_age_seconds: int,
    ) -> bool:
        """Whether ``conv``'s newest candidate message was dropped before its turn.

        The per-conversation form of ``_MASKED_INBOUND_SQL``: the newest message
        is a completed ``BOT`` outcome whose outbound command quotes a different
        inbound than the newest candidate message, so that candidate message
        arrived while the outcome's turn held the per-chat mutex and never got a
        turn of its own.

        The reconcile tick re-runs this against freshly read state before it acts
        on such a candidate: a turn enqueued since the scan may already have
        answered the message, and then the newest outcome quotes it and this
        returns False.

        This answers only "did the newest candidate message get a turn?".  The
        sweep's outer guards (mode, OPEN status, live per-chat lock) are not part
        of it, so a HUMAN-owned conversation can still answer True — the tick
        re-checks ``run_start_guard`` and the lock on the fresh row before it
        enqueues anything.
        """
        found = await self.db.scalar(
            text(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM conversations c
                     WHERE c.id = :conv_id
                       AND ({_MASKED_INBOUND_SQL})
                )
                """
            ),
            {
                "conv_id": conv.id,
                "now_minus_grace": now - timedelta(seconds=grace_seconds),
                "now_minus_max_age": now - timedelta(seconds=max_age_seconds),
            },
        )
        return bool(found)
