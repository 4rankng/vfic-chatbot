"""Data-access layer for dashboard metrics.

Verbatim ports of the count / funnel / ingest-health queries DashboardService
previously ran inline, so the service owns only viewer-scoping + result assembly
(business logic) and the Redis telemetry call.

Each metric branches on ``recruiter_id``: ``None`` = global (admin), a uid = scoped
to that recruiter's assigned-or-unassigned rows. The "admin = global, recruiter =
assigned" rule is decided by the SERVICE and passed in; this repo just runs the SQL.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.viewer_scope import (
    support_account_sql,
    support_leads_sql,
    viewer_scope_sql,
)

_SUPPORT_ACCOUNT_SCOPED = support_account_sql("c.")
_SUPPORT_LEADS_SCOPED = support_leads_sql("l.")


class DashboardRepository:
    """Read-only dashboard counts, funnel, and ingest-health queries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _scoped_scalar(
        self,
        recruiter_id: str | None,
        global_sql: str,
        scoped_sql: str,
    ) -> int | None:
        """Run a single-value query, branching global vs viewer-scoped.

        The two SQL strings differ because the scoped path joins the scope table
        (e.g. leads/conversations) that the global path does not need, so each call
        site passes both verbatim. Only the branch + ``{"uid": ...}`` plumbing is
        shared, which is what had been copy-pasted across the count metrics.
        """
        if recruiter_id is None:
            return await self.db.scalar(text(global_sql))
        return await self.db.scalar(text(scoped_sql), {"uid": recruiter_id})

    # The five headline count keys, in the order core_counts returns them.
    _CORE_COUNT_KEYS: tuple[str, ...] = (
        "open_conversations",
        "hot_leads",
        "pending_followups",
        "failed_sends",
        "bot_errors",
    )

    async def core_counts(self, recruiter_id: str | None = None) -> dict[str, int]:
        """The five headline dashboard counters in ONE round-trip / ONE snapshot.

        Each counter is a scalar subquery anchored on its own table (the same
        shape ``attention_counters`` uses), so counts stay exact with no row
        multiplication — every join here is 1:1 on a primary/unique key. Each
        subquery carries its own viewer scope; for admin (``recruiter_id is
        None``) the scope fragments are ``(TRUE)`` no-ops.
        """
        scoped = recruiter_id is not None
        c_scope = (
            viewer_scope_sql("c.") + " AND " + _SUPPORT_ACCOUNT_SCOPED if scoped else "(TRUE)"
        )
        l_scope = viewer_scope_sql("l.") + " AND " + _SUPPORT_LEADS_SCOPED if scoped else "(TRUE)"
        params: dict[str, str] = {}
        if scoped:
            params["uid"] = recruiter_id

        sql = (
            "SELECT "
            "(SELECT count(*) FROM conversations c "
            "WHERE c.status = 'OPEN' AND " + c_scope + ") AS open_conversations, "
            "(SELECT count(*) FROM leads l "
            "WHERE l.lead_score = 'hot' AND " + l_scope + ") AS hot_leads, "
            "(SELECT count(*) FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
            "WHERE f.status = 'PENDING' AND " + l_scope + ") AS pending_followups, "
            "(SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.delivery_status = 'FAILED' AND " + c_scope + ") AS failed_sends, "
            "(SELECT count(*) FROM bot_runs b JOIN conversations c ON c.id = b.conversation_id "
            "WHERE b.outcome = 'ERROR' AND " + c_scope + ") AS bot_errors"
        )
        row = (await self.db.execute(text(sql), params)).mappings().one()
        return {k: int(row[k] or 0) for k in self._CORE_COUNT_KEYS}

    async def bot_run_summary(self, recruiter_id: str | None = None) -> dict[str, float | int]:
        """Aggregate bot-turn health over the LAST 24 HOURS (not all-time).

        Bounded on ``started_at`` so the aggregate rides the
        ``bot_runs_started_at_idx`` index instead of scanning the whole,
        never-pruned audit table; ``bot_runs`` rows persist forever, so an
        unbounded version got slower every month. Callers must present these
        numbers as 24-hour figures.
        """
        sql = (
            "SELECT "
            "count(*)::int AS total, "
            "count(*) FILTER (WHERE b.outcome = 'SENT')::int AS sent, "
            "count(*) FILTER (WHERE b.outcome = 'SUPPRESSED')::int AS suppressed, "
            "count(*) FILTER (WHERE b.outcome = 'ERROR')::int AS errors, "
            "coalesce(avg(extract(epoch FROM (b.ended_at - b.started_at))) "
            "FILTER (WHERE b.ended_at IS NOT NULL), 0)::float AS avg_seconds "
            "FROM bot_runs b"
        )
        params = {}
        if recruiter_id is not None:
            sql += " JOIN conversations c ON c.id = b.conversation_id AND " + viewer_scope_sql(
                "c."
            )
            params["uid"] = recruiter_id
        sql += " WHERE b.started_at > now() - interval '24 hours'"
        row = (await self.db.execute(text(sql), params)).mappings().one()
        return {
            "total": int(row["total"] or 0),
            "sent": int(row["sent"] or 0),
            "suppressed": int(row["suppressed"] or 0),
            "errors": int(row["errors"] or 0),
            "avg_seconds": float(row["avg_seconds"] or 0.0),
        }

    async def leads_by_stage(self, recruiter_id: str | None = None) -> dict[str, int]:
        if recruiter_id is None:
            rows = (
                await self.db.execute(
                    text("SELECT lead_stage, count(*) FROM leads GROUP BY lead_stage")
                )
            ).all()
        else:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT lead_stage, count(*) FROM leads "
                        "WHERE " + viewer_scope_sql("") + " AND " + support_leads_sql("") + " "
                        "GROUP BY lead_stage"
                    ),
                    {"uid": recruiter_id},
                )
            ).all()
        return {r[0]: int(r[1]) for r in rows}

    async def count_human_conversations(self, recruiter_id: str | None = None) -> int | None:
        return await self._scoped_scalar(
            recruiter_id,
            "SELECT count(*) FROM conversations WHERE mode = 'HUMAN'",
            "SELECT count(*) FROM conversations WHERE mode = 'HUMAN' AND "
            + viewer_scope_sql("")
            + " AND "
            + support_account_sql(""),
        )

    async def knowledge_stage_counts(self) -> dict[str, int]:
        """``{stage: count}`` for all knowledge_documents (admin ingest health)."""
        rows = (
            await self.db.execute(
                text(
                    "SELECT stage, count(*) FROM knowledge_documents GROUP BY stage ORDER BY stage"
                )
            )
        ).all()
        return {str(r[0]): int(r[1]) for r in rows}

    async def count_stuck_documents(self, stages: list[str]) -> int | None:
        """Docs in a processing stage not updated for >10 min."""
        return await self.db.scalar(
            text(
                "SELECT count(*) FROM knowledge_documents "
                "WHERE stage = ANY(CAST(:stages AS text[])) "
                "AND updated_at < now() - interval '10 minutes'"
            ),
            {"stages": stages},
        )

    async def recent_ingest_issues(self, stages: list[str], limit: int = 6) -> list:
        """FAILED or stuck documents, newest first (mapping rows for the service to format)."""
        return (
            await self.db.execute(
                text(
                    "SELECT id, file_name, project_id, status, stage, "
                    "GREATEST(0, floor(extract(epoch from (now() - updated_at)) / 60))::int AS minutes_since_update, "
                    "left(coalesce(error, ''), 240) AS error "
                    "FROM knowledge_documents "
                    "WHERE status = 'FAILED' "
                    "OR (stage = ANY(CAST(:stages AS text[])) AND updated_at < now() - interval '10 minutes') "
                    "ORDER BY updated_at DESC LIMIT :limit"
                ),
                {"stages": stages, "limit": limit},
            )
        ).mappings()

    # --- Concurrent-load monitoring (300-concurrency readiness) ---

    async def active_turns(self) -> int:
        """Conversations currently processing a bot turn (lock held)."""
        return (
            await self.db.scalar(
                text("SELECT count(*) FROM conversations WHERE bot_locked_until > now()")
            )
            or 0
        )

    async def bot_run_p95_latency(self, days: int = 7) -> float:
        """95th percentile turn duration (seconds) from completed bot_runs in the last *days* days."""
        return float(
            await self.db.scalar(
                text(
                    "SELECT coalesce(percentile_cont(0.95) "
                    "WITHIN GROUP (ORDER BY extract(epoch FROM (ended_at - started_at))), 0) "
                    "FROM bot_runs "
                    "WHERE outcome IN ('SENT','SUPPRESSED') "
                    "AND started_at > now() - make_interval(days => :days) "
                    "AND ended_at IS NOT NULL"
                ),
                {"days": days},
            )
            or 0.0
        )

    async def recent_turns_count(self, minutes: int = 5) -> int:
        """Bot turns started in the last N minutes (near-real-time throughput)."""
        return (
            await self.db.scalar(
                text(
                    "SELECT count(*) FROM bot_runs "
                    "WHERE started_at > now() - make_interval(mins => :minutes)"
                ),
                {"minutes": minutes},
            )
            or 0
        )

    # --- Recruiter attention dashboard (read-only, viewer-scoped) -------------
    #
    # Reason precedence (Phase 1 spec, descending). The repository owns the SQL
    # form of each predicate; the service owns precedence ordering and assembly.
    # Viewer scope is applied to BOTH the anchor table AND every enrichment join
    # (Join & Dedup Contract) — leads and conversations carry INDEPENDENT
    # assigned_recruiter_id columns. The lead↔conversation link is the canonical
    # contact_id (Alembic 0047), replacing the legacy Zalo-only soft match.
    #
    # Counter-to-reason mapping (documented for the reviewer):
    #   needs_reply = REPLY_OVERDUE + WAITING_REPLY + HUMAN_ESCALATION
    #   overdue     = REPLY_OVERDUE + FOLLOWUP_OVERDUE
    #   due_today   = FOLLOWUP_TODAY
    #   priority    = PRIORITY_NO_ACTION + DELIVERY_REVIEW + STALLED
    #   unread      = UNREAD

    @staticmethod
    def _vn_today_predicate(column: str) -> str:
        """Vietnam-calendar-day equality for ``column`` (a timestamptz).

        Storage is ``DateTime(timezone=True)``; comparing ``::date`` in UTC would
        split a VN day across two UTC days. The mandated form converts both sides
        to Asia/Ho_Chi_Minh before casting to date (Phase 1 spec Timezone section).
        No naive Python date math — the conversion happens server-side.
        """
        return (
            f"({column} AT TIME ZONE 'Asia/Ho_Chi_Minh')::date "
            f"= (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date"
        )

    @staticmethod
    def _human_unanswered_predicate(alias: str = "c.") -> str:
        """Canonical recruiter-response queue membership for raw SQL reads."""
        return (
            f"{alias}status = 'OPEN' "
            f"AND {alias}mode = 'HUMAN' "
            f"AND {alias}last_inbound_at IS NOT NULL "
            f"AND ({alias}last_outbound_at IS NULL "
            f"OR {alias}last_inbound_at > {alias}last_outbound_at)"
        )

    # The five counter keys, in the order AttentionCounters expects them.
    _COUNTER_KEYS: tuple[str, ...] = (
        "needs_reply",
        "overdue",
        "due_today",
        "priority",
        "unread",
    )

    async def attention_counters(self, recruiter_id: str | None) -> dict[str, int]:
        """Five exact viewer-scoped counters in ONE round-trip / ONE snapshot.

        Each counter is a scalar subquery anchored on the correct table per the
        Reason Precedence table (conversations vs leads vs follow_up_tasks), so
        counts are exact with no row multiplication. The spec's "count(*)
        FILTER over a unified join" framing would multiply rows on the
        conv<->lead and lead<->followup joins and corrupt the counts; scalar
        subqueries in a single SELECT honor the real intent (1 round-trip, 1
        snapshot) while staying correct. Viewer scope is applied to BOTH sides
        of every join (Join & Dedup Contract).
        """
        # Shared viewer-scope fragments. For admin (recruiter_id is None) these
        # are replaced by "TRUE" so the predicates are no-ops.
        c_scope = (
            viewer_scope_sql("c.") + " AND " + _SUPPORT_ACCOUNT_SCOPED
            if recruiter_id is not None
            else "(TRUE)"
        )
        l_scope = (
            viewer_scope_sql("l.") + " AND " + _SUPPORT_LEADS_SCOPED
            if recruiter_id is not None
            else "(TRUE)"
        )
        params: dict[str, str] = {}
        if recruiter_id is not None:
            params["uid"] = recruiter_id

        vn_today_due = self._vn_today_predicate("f.due_at")

        # --- Conversation-anchored predicates (viewer scope on c.) -----------
        human_unanswered = (
            "SELECT count(*) FROM conversations c "
            "WHERE "
            + self._human_unanswered_predicate()
            + " AND "
            + c_scope
        )
        # REPLY_OVERDUE: unanswered inbound age >= 30 minutes.
        reply_overdue = (
            "SELECT count(*) FROM conversations c "
            "WHERE "
            + self._human_unanswered_predicate()
            + " "
            "AND c.last_inbound_at < now() - interval '30 minutes' "
            "AND " + c_scope
        )
        # UNREAD: open conversation with unread_count > 0.
        unread = (
            "SELECT count(*) FROM conversations c "
            "WHERE c.status = 'OPEN' AND c.unread_count > 0 AND " + c_scope
        )
        # DELIVERY_REVIEW: latest outbound (BOT/RECRUITER) message is FAILED or
        # SEND_UNKNOWN. The lateral subquery picks the single latest outbound
        # row by created_at DESC; the sender predicate is mandatory so a WORKER
        # row in PENDING/SENDING never registers. SEND_UNKNOWN is intentionally
        # non-reconciled → permanent urgency until manual action.
        delivery_review = (
            "SELECT count(*) FROM conversations c "
            "WHERE EXISTS ("
            "  SELECT 1 FROM messages m "
            "  WHERE m.conversation_id = c.id "
            "  AND m.sender IN ('BOT','RECRUITER') "
            "  AND m.delivery_status IN ('FAILED','SEND_UNKNOWN') "
            "  AND m.id = ("
            "    SELECT m2.id FROM messages m2 "
            "    WHERE m2.conversation_id = c.id "
            "    AND m2.sender IN ('BOT','RECRUITER') "
            "    ORDER BY m2.created_at DESC LIMIT 1)) "
            "AND "
            + self._human_unanswered_predicate()
            + " AND "
            + c_scope
        )

        # --- Lead-anchored predicates (viewer scope on l.) -------------------
        # Excludes SKIPPED leads (LeadStage) from all lead-anchored reasons.
        # Leads with no linked contact are eligible ONLY for lead-anchored reasons.
        not_skipped = "l.lead_stage <> 'SKIPPED'"

        # FOLLOWUP_OVERDUE: pending follow-up past due. Anchor follow_up_tasks,
        # scope on the joined lead.
        followup_overdue = (
            "SELECT count(*) FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
            "WHERE f.status = 'PENDING' AND f.due_at < now() "
            "AND " + not_skipped + " AND " + l_scope
        )
        # FOLLOWUP_TODAY: pending follow-up due on the VN calendar day.
        followup_today = (
            "SELECT count(*) FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
            "WHERE f.status = 'PENDING' AND " + vn_today_due + " "
            "AND " + not_skipped + " AND " + l_scope
        )
        # STALLED: no activity for 48h. Active = lead updated in 48h OR a linked
        # conversation had inbound/outbound in 48h. NOT (updated_at alone — it
        # mutates on any write and misclassifies cold-but-edited leads).
        stalled = (
            "SELECT count(*) FROM leads l "
            "WHERE " + not_skipped + " "
            "AND NOT ("
            "  l.updated_at > now() - interval '48 hours' "
            "  OR EXISTS ("
            "    SELECT 1 FROM conversations c "
            "    WHERE c.contact_id = l.contact_id "
            "    AND (c.last_inbound_at > now() - interval '48 hours' "
            "         OR c.last_outbound_at > now() - interval '48 hours'))) "
            "AND " + l_scope
        )
        # PRIORITY_NO_ACTION: hot OR (REGISTERED within 7d), with no future
        # pending follow-up AND next_action_at not in the future AND no RECRUITER
        # message in the linked conversation within 24h. The 7-day gate prevents
        # terminal REGISTERED leads from flooding the counter forever. Uses a
        # RECRUITER-message EXISTS (not last_outbound_at, which includes BOT and
        # would hide genuinely-ignored hot leads).
        priority_no_action = (
            "SELECT count(*) FROM leads l "
            "WHERE " + not_skipped + " "
            "AND (l.lead_score = 'hot' "
            "     OR (l.lead_stage = 'REGISTERED' "
            "         AND l.created_at >= now() - interval '7 days')) "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM follow_up_tasks f "
            "  WHERE f.lead_id = l.id AND f.status = 'PENDING' AND f.due_at > now()) "
            "AND (l.next_action_at IS NULL OR l.next_action_at <= now()) "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM conversations c "
            "  WHERE c.contact_id = l.contact_id "
            "  AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id "
            "              AND m.sender = 'RECRUITER' "
            "              AND m.created_at > now() - interval '24 hours')) "
            "AND " + l_scope
        )

        # Single statement → one round-trip, one snapshot. Each subquery is
        # independent and exact (no cross-anchor row multiplication).
        sql = (
            "SELECT "
            f"({human_unanswered}) AS needs_reply, "
            f"({reply_overdue}) + ({followup_overdue}) AS overdue, "
            f"({followup_today}) AS due_today, "
            f"({priority_no_action}) + ({delivery_review}) + ({stalled}) AS priority, "
            f"({unread}) AS unread"
        )
        row = (await self.db.execute(text(sql), params)).mappings().one()
        return {k: int(row[k] or 0) for k in self._COUNTER_KEYS}

    async def attention_rows(
        self,
        recruiter_id: str | None,
        queue: str,
        limit: int = 8,
    ) -> list:
        """Bounded read for the ``immediate`` or ``today`` queue.

        Returns mapping rows with every field ``AttentionItemOut`` needs EXCEPT
        the message body (PII minimization). Computes ``urgency_at``, ``reason``,
        ``key``, and ``action`` server-side and applies dedup so each candidate
        appears once under its highest-precedence reason. Sorted by precedence
        then ``urgency_at`` ascending.

        ``queue`` is ``"immediate"`` (DELIVERY_REVIEW, HUMAN_ESCALATION,
        REPLY_OVERDUE, FOLLOWUP_OVERDUE, WAITING_REPLY, UNREAD) or ``"today"``
        (FOLLOWUP_TODAY, PRIORITY_NO_ACTION, STALLED). The grouping mirrors how
        the frontend splits urgency: immediate needs action now, today is the
        day's planned work.
        """
        if queue not in ("immediate", "today"):
            raise ValueError(f"unknown attention queue: {queue!r}")

        c_scope = (
            viewer_scope_sql("c.") + " AND " + _SUPPORT_ACCOUNT_SCOPED
            if recruiter_id is not None
            else "(TRUE)"
        )
        l_scope = (
            viewer_scope_sql("l.") + " AND " + _SUPPORT_LEADS_SCOPED
            if recruiter_id is not None
            else "(TRUE)"
        )
        params: dict[str, object] = {"limit": limit}
        if recruiter_id is not None:
            params["uid"] = recruiter_id
        vn_today_due = self._vn_today_predicate("f.due_at")
        not_skipped = "l.lead_stage <> 'SKIPPED'"
        human_unanswered = self._human_unanswered_predicate()

        # Each reason is a CTE projecting a uniform row shape plus a fixed
        # integer precedence (smaller = higher priority, matching the Reason
        # Precedence list) and the urgency timestamp to sort by. dedup_key is
        # conversation uuid text when present, else 'lead:<id>'.
        # The lateral lead pick uses MAX(l.updated_at) per the existing
        # _conversation_for_lead helper (lead/service.py:340-347) tie-break.

        # Conversation-anchored reasons. Enrichment (name/phone/stage)
        # comes from the latest-updated lead matching c.contact_id, with lead
        # viewer scope applied independently (Join & Dedup Contract: if the
        # conversation and lead disagree on ownership, the row is dropped).
        delivery_review_cte = (
            "delivery_review AS ("
            "  SELECT c.id AS conversation_id, NULL::bigint AS lead_id, "
            "  'DELIVERY_REVIEW'::text AS reason, 1 AS precedence, "
            "  m.created_at AS urgency_at, m.delivery_status::text AS delivery_status, "
            "  c.last_inbound_at, NULL::timestamptz AS due_at "
            "  FROM conversations c "
            "  JOIN LATERAL ("
            "    SELECT m2.id, m2.created_at, m2.delivery_status FROM messages m2 "
            "    WHERE m2.conversation_id = c.id AND m2.sender IN ('BOT','RECRUITER') "
            "    ORDER BY m2.created_at DESC LIMIT 1) m ON true "
            "  WHERE m.delivery_status IN ('FAILED','SEND_UNKNOWN') AND "
            + human_unanswered
            + " AND "
            + c_scope
            + ")"
        )
        human_esc_cte = (
            "human_escalation AS ("
            "  SELECT c.id AS conversation_id, NULL::bigint AS lead_id, "
            "  'HUMAN_ESCALATION'::text AS reason, 2 AS precedence, "
            "  coalesce(c.last_inbound_at, c.updated_at) AS urgency_at, "
            "  NULL::text AS delivery_status, c.last_inbound_at, "
            "  NULL::timestamptz AS due_at "
            "  FROM conversations c "
            "  WHERE c.needs_human AND "
            + human_unanswered
            + " AND "
            + c_scope
            + ")"
        )
        reply_overdue_cte = (
            "reply_overdue AS ("
            "  SELECT c.id AS conversation_id, NULL::bigint AS lead_id, "
            "  'REPLY_OVERDUE'::text AS reason, 3 AS precedence, "
            "  c.last_inbound_at AS urgency_at, NULL::text AS delivery_status, "
            "  c.last_inbound_at, NULL::timestamptz AS due_at "
            "  FROM conversations c "
            "  WHERE "
            + human_unanswered
            + " AND c.last_inbound_at < now() - interval '30 minutes' AND "
            + c_scope
            + ")"
        )
        followup_overdue_cte = (
            "followup_overdue AS ("
            "  SELECT c.id AS conversation_id, l.id AS lead_id, "
            "  'FOLLOWUP_OVERDUE'::text AS reason, 4 AS precedence, "
            "  f.due_at AS urgency_at, NULL::text AS delivery_status, "
            "  c.last_inbound_at, f.due_at AS due_at "
            "  FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
            "  LEFT JOIN conversations c ON c.contact_id = l.contact_id AND " + c_scope + " "
            "  WHERE f.status = 'PENDING' AND f.due_at < now() "
            "  AND " + not_skipped + " AND " + l_scope + ")"
        )
        waiting_reply_cte = (
            "waiting_reply AS ("
            "  SELECT c.id AS conversation_id, NULL::bigint AS lead_id, "
            "  'WAITING_REPLY'::text AS reason, 5 AS precedence, "
            "  c.last_inbound_at AS urgency_at, NULL::text AS delivery_status, "
            "  c.last_inbound_at, NULL::timestamptz AS due_at "
            "  FROM conversations c "
            "  WHERE "
            + human_unanswered
            + " AND c.last_inbound_at >= now() - interval '30 minutes' AND "
            + c_scope
            + ")"
        )
        priority_no_action_cte = (
            "priority_no_action AS ("
            "  SELECT c.id AS conversation_id, l.id AS lead_id, "
            "  'PRIORITY_NO_ACTION'::text AS reason, 6 AS precedence, "
            "  l.created_at AS urgency_at, NULL::text AS delivery_status, "
            "  c.last_inbound_at, NULL::timestamptz AS due_at "
            "  FROM leads l "
            "  LEFT JOIN conversations c ON c.contact_id = l.contact_id AND " + c_scope + " "
            "  WHERE " + not_skipped + " "
            "  AND (l.lead_score = 'hot' OR (l.lead_stage = 'REGISTERED' "
            "       AND l.created_at >= now() - interval '7 days')) "
            "  AND NOT EXISTS (SELECT 1 FROM follow_up_tasks f WHERE f.lead_id = l.id "
            "    AND f.status = 'PENDING' AND f.due_at > now()) "
            "  AND (l.next_action_at IS NULL OR l.next_action_at <= now()) "
            "  AND NOT EXISTS (SELECT 1 FROM conversations c2 WHERE c2.contact_id = l.contact_id "
            "    AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c2.id "
            "      AND m.sender = 'RECRUITER' AND m.created_at > now() - interval '24 hours')) "
            "  AND " + l_scope + ")"
        )
        followup_today_cte = (
            "followup_today AS ("
            "  SELECT c.id AS conversation_id, l.id AS lead_id, "
            "  'FOLLOWUP_TODAY'::text AS reason, 7 AS precedence, "
            "  f.due_at AS urgency_at, NULL::text AS delivery_status, "
            "  c.last_inbound_at, f.due_at AS due_at "
            "  FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
            "  LEFT JOIN conversations c ON c.contact_id = l.contact_id AND " + c_scope + " "
            "  WHERE f.status = 'PENDING' AND " + vn_today_due + " "
            "  AND " + not_skipped + " AND " + l_scope + ")"
        )
        unread_cte = (
            "unread AS ("
            "  SELECT c.id AS conversation_id, NULL::bigint AS lead_id, "
            "  'UNREAD'::text AS reason, 8 AS precedence, "
            "  coalesce(c.last_inbound_at, c.updated_at) AS urgency_at, "
            "  NULL::text AS delivery_status, c.last_inbound_at, "
            "  NULL::timestamptz AS due_at "
            "  FROM conversations c "
            "  WHERE c.status = 'OPEN' AND c.unread_count > 0 AND " + c_scope + ")"
        )
        stalled_cte = (
            "stalled AS ("
            "  SELECT c.id AS conversation_id, l.id AS lead_id, "
            "  'STALLED'::text AS reason, 9 AS precedence, "
            "  l.updated_at AS urgency_at, NULL::text AS delivery_status, "
            "  c.last_inbound_at, NULL::timestamptz AS due_at "
            "  FROM leads l "
            "  LEFT JOIN conversations c ON c.contact_id = l.contact_id AND " + c_scope + " "
            "  WHERE " + not_skipped + " "
            "  AND NOT (l.updated_at > now() - interval '48 hours' "
            "    OR EXISTS (SELECT 1 FROM conversations c2 WHERE c2.contact_id = l.contact_id "
            "      AND (c2.last_inbound_at > now() - interval '48 hours' "
            "           OR c2.last_outbound_at > now() - interval '48 hours'))) "
            "  AND " + l_scope + ")"
        )

        immediate_ctes = [
            delivery_review_cte,
            human_esc_cte,
            reply_overdue_cte,
            followup_overdue_cte,
            waiting_reply_cte,
            unread_cte,
        ]
        today_ctes = [followup_today_cte, priority_no_action_cte, stalled_cte]
        ctes = immediate_ctes if queue == "immediate" else today_ctes

        # UNION ALL candidate rows → dedup by stable key keeping the
        # highest-precedence (min precedence int) reason via ROW_NUMBER, then
        # enrich with lead PII through a LATERAL join scoped on both sides.
        # dedup_key: conversation uuid text when present, else 'lead:<lead_id>'.
        union_sql = " UNION ALL ".join(f"SELECT * FROM {name.split(' AS ')[0]}" for name in ctes)
        dedup_sql = (
            "candidates AS ("
            "  SELECT conversation_id, lead_id, reason, precedence, urgency_at, "
            "  delivery_status, last_inbound_at, due_at, "
            "  coalesce(conversation_id::text, 'lead:' || lead_id::text) AS dedup_key, "
            "  row_number() OVER ("
            "    PARTITION BY coalesce(conversation_id::text, 'lead:' || lead_id::text) "
            "    ORDER BY precedence) AS rn "
            "  FROM (" + union_sql + ") u)"
        )

        # Enrichment: for each surviving candidate, pull name/phone/
        # desired_job/stage/score from the matching lead. Conversation-anchored
        # rows match via leads.contact_id = c.contact_id (latest updated_at wins,
        # tie-break per Join & Dedup Contract); lead-anchored rows already have
        # the lead_id. viewer_scope applied to the enrichment lead independently.
        # The recruiter dashboard needs the full phone number for follow-up.
        sql = (
            "WITH " + ", ".join(ctes + [dedup_sql]) + " "
            "SELECT cand.reason, cand.urgency_at, cand.conversation_id, cand.lead_id, "
            "el.name, el.phone, el.desired_job, el.lead_stage, el.lead_score, "
            "cand.last_inbound_at, cand.due_at, cand.delivery_status "
            "FROM candidates cand "
            "LEFT JOIN LATERAL ("
            "  SELECT l.name, l.phone, l.desired_job, "
            "  l.lead_stage::text AS lead_stage, l.lead_score::text AS lead_score "
            "  FROM leads l "
            + self._enrichment_join(c_scope, l_scope)
            + " ORDER BY l.updated_at DESC LIMIT 1) el ON true "
            "WHERE cand.rn = 1 "
            "ORDER BY cand.precedence ASC, cand.urgency_at ASC "
            "LIMIT :limit"
        )
        return list((await self.db.execute(text(sql), params)).mappings())

    async def attention_reason_page(
        self,
        recruiter_id: str | None,
        *,
        reason: str,
        channel_provider: str | None,
        page: int,
        per_page: int,
    ) -> tuple[list[uuid.UUID], int]:
        """Return one exact, provider-scoped attention-reason page.

        Unlike the bounded dashboard widget query, this continuation query
        selects only the requested reason and applies channel/viewer predicates
        before deduplication, exact counting, and pagination. The total CTE is
        left-joined to the requested page so an out-of-range page still returns
        the non-zero exact total. Reason continuations are intentionally
        independent: a conversation matching a higher-precedence dashboard
        reason remains eligible when a caller explicitly filters a lower one.
        """
        reason_sql = self._attention_reason_source(reason, recruiter_id, channel_provider)
        params: dict[str, object] = {
            "channel_provider": channel_provider,
            "limit": per_page,
            "offset": (page - 1) * per_page,
        }
        if recruiter_id is not None:
            params["uid"] = recruiter_id

        sql = (
            "WITH reason_rows AS ("
            + reason_sql
            + "), ranked AS ("
            "  SELECT conversation_id, urgency_at, "
            "  row_number() OVER (PARTITION BY conversation_id "
            "    ORDER BY urgency_at ASC, conversation_id ASC) AS rn "
            "  FROM reason_rows"
            "), filtered AS ("
            "  SELECT conversation_id, urgency_at FROM ranked WHERE rn = 1"
            "), totals AS ("
            "  SELECT count(*)::int AS total FROM filtered"
            "), page_rows AS ("
            "  SELECT conversation_id, urgency_at FROM filtered "
            "  ORDER BY urgency_at ASC, conversation_id ASC "
            "  OFFSET :offset LIMIT :limit"
            ") "
            "SELECT page_rows.conversation_id, totals.total "
            "FROM totals LEFT JOIN page_rows ON true "
            "ORDER BY page_rows.urgency_at ASC, page_rows.conversation_id ASC"
        )
        rows = list((await self.db.execute(text(sql), params)).mappings())
        if not rows:
            return [], 0
        total = int(rows[0]["total"] or 0)
        ids = [uuid.UUID(str(row["conversation_id"])) for row in rows if row["conversation_id"]]
        return ids, total

    @staticmethod
    def _provider_scope(alias: str, channel_provider: str | None) -> str:
        """SQL identity predicate for one channel filter value.

        Mirrors ``ConversationRepository._channel_filter_condition`` so the
        reason-scoped inbox page and the plain list agree: ``tingting_oa`` is the
        employee-support Zalo OA account, not a provider, and the plain
        ``zalo_oa`` badge excludes it so the two badges stay disjoint. Account
        keys are code-owned constants (no user input), so they are inlined like
        ``viewer_scope`` does; the generic branch binds ``:channel_provider``.
        """
        from app.channels import types as ct
        from app.channels.types import TINGTING_OA_ACCOUNT_KEY

        if channel_provider == "tingting_oa":
            return (
                f"{alias}provider = '{ct.PROVIDER_ZALO_OA}' "
                f"AND {alias}account_key = '{TINGTING_OA_ACCOUNT_KEY}'"
            )
        if channel_provider == "zalo_oa":
            return (
                f"{alias}provider = '{ct.PROVIDER_ZALO_OA}' "
                f"AND ({alias}account_key IS NULL "
                f"OR {alias}account_key <> '{TINGTING_OA_ACCOUNT_KEY}')"
            )
        return (
            "(CAST(:channel_provider AS text) IS NULL "
            f"OR {alias}provider = CAST(:channel_provider AS text))"
        )

    def _attention_reason_source(
        self, reason: str, recruiter_id: str | None, channel_provider: str | None
    ) -> str:
        """SQL source for one canonical dashboard reason.

        Every branch projects ``conversation_id`` and ``urgency_at``. Lead-only
        dashboard items are intentionally absent because the conversation list
        can open only rows backed by a real, viewer-visible conversation.
        """
        c_scope = (
            viewer_scope_sql("c.") + " AND " + _SUPPORT_ACCOUNT_SCOPED
            if recruiter_id is not None
            else "(TRUE)"
        )
        l_scope = (
            viewer_scope_sql("l.") + " AND " + _SUPPORT_LEADS_SCOPED
            if recruiter_id is not None
            else "(TRUE)"
        )
        provider_scope = self._provider_scope("ci.", channel_provider)
        related_provider_scope = self._provider_scope("ci2.", channel_provider)
        conversation_from = (
            "FROM conversations c "
            "JOIN contact_channel_identities ci ON ci.id = c.channel_identity_id "
        )
        lead_conversation_from = (
            "JOIN conversations c ON c.contact_id = l.contact_id AND "
            + c_scope
            + " JOIN contact_channel_identities ci ON ci.id = c.channel_identity_id "
        )
        not_skipped = "l.lead_stage <> 'SKIPPED'"
        vn_today_due = self._vn_today_predicate("f.due_at")
        human_unanswered = self._human_unanswered_predicate()

        sources = {
            "DELIVERY_REVIEW": (
                "SELECT c.id AS conversation_id, m.created_at AS urgency_at "
                + conversation_from
                + "JOIN LATERAL ("
                "  SELECT m2.created_at, m2.delivery_status FROM messages m2 "
                "  WHERE m2.conversation_id = c.id "
                "  AND m2.sender IN ('BOT','RECRUITER') "
                "  ORDER BY m2.created_at DESC LIMIT 1"
                ") m ON true "
                "WHERE m.delivery_status IN ('FAILED','SEND_UNKNOWN') AND "
                + human_unanswered
                + " AND "
                + c_scope
                + " AND "
                + provider_scope
            ),
            "HUMAN_ESCALATION": (
                "SELECT c.id AS conversation_id, "
                "coalesce(c.last_inbound_at, c.updated_at) AS urgency_at "
                + conversation_from
                + "WHERE c.needs_human AND "
                + human_unanswered
                + " AND "
                + c_scope
                + " AND "
                + provider_scope
            ),
            "REPLY_OVERDUE": (
                "SELECT c.id AS conversation_id, c.last_inbound_at AS urgency_at "
                + conversation_from
                + "WHERE "
                + human_unanswered
                + " AND c.last_inbound_at < now() - interval '30 minutes' AND "
                + c_scope
                + " AND "
                + provider_scope
            ),
            "FOLLOWUP_OVERDUE": (
                "SELECT c.id AS conversation_id, f.due_at AS urgency_at "
                "FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
                + lead_conversation_from
                + "WHERE f.status = 'PENDING' AND f.due_at < now() AND "
                + not_skipped
                + " AND "
                + l_scope
                + " AND "
                + provider_scope
            ),
            "WAITING_REPLY": (
                "SELECT c.id AS conversation_id, c.last_inbound_at AS urgency_at "
                + conversation_from
                + "WHERE "
                + human_unanswered
                + " AND c.last_inbound_at >= now() - interval '30 minutes' AND "
                + c_scope
                + " AND "
                + provider_scope
            ),
            "PRIORITY_NO_ACTION": (
                "SELECT c.id AS conversation_id, l.created_at AS urgency_at "
                "FROM leads l "
                + lead_conversation_from
                + "WHERE "
                + not_skipped
                + " AND (l.lead_score = 'hot' OR (l.lead_stage = 'REGISTERED' "
                "AND l.created_at >= now() - interval '7 days')) "
                "AND NOT EXISTS (SELECT 1 FROM follow_up_tasks f WHERE f.lead_id = l.id "
                "AND f.status = 'PENDING' AND f.due_at > now()) "
                "AND (l.next_action_at IS NULL OR l.next_action_at <= now()) "
                "AND NOT EXISTS (SELECT 1 FROM conversations c2 "
                "JOIN contact_channel_identities ci2 ON ci2.id = c2.channel_identity_id "
                "WHERE c2.contact_id = l.contact_id AND "
                + related_provider_scope
                + " AND EXISTS ("
                "SELECT 1 FROM messages m WHERE m.conversation_id = c2.id "
                "AND m.sender = 'RECRUITER' "
                "AND m.created_at > now() - interval '24 hours')) AND "
                + l_scope
                + " AND "
                + provider_scope
            ),
            "FOLLOWUP_TODAY": (
                "SELECT c.id AS conversation_id, f.due_at AS urgency_at "
                "FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
                + lead_conversation_from
                + "WHERE f.status = 'PENDING' AND "
                + vn_today_due
                + " AND "
                + not_skipped
                + " AND "
                + l_scope
                + " AND "
                + provider_scope
            ),
            "UNREAD": (
                "SELECT c.id AS conversation_id, "
                "coalesce(c.last_inbound_at, c.updated_at) AS urgency_at "
                + conversation_from
                + "WHERE c.status = 'OPEN' AND c.unread_count > 0 AND "
                + c_scope
                + " AND "
                + provider_scope
            ),
            "STALLED": (
                "SELECT c.id AS conversation_id, l.updated_at AS urgency_at "
                "FROM leads l "
                + lead_conversation_from
                + "WHERE "
                + not_skipped
                + " AND NOT (l.updated_at > now() - interval '48 hours' "
                "OR EXISTS (SELECT 1 FROM conversations c2 "
                "JOIN contact_channel_identities ci2 ON ci2.id = c2.channel_identity_id "
                "WHERE c2.contact_id = l.contact_id AND "
                + related_provider_scope
                + " "
                "AND (c2.last_inbound_at > now() - interval '48 hours' "
                "OR c2.last_outbound_at > now() - interval '48 hours'))) AND "
                + l_scope
                + " AND "
                + provider_scope
            ),
        }
        try:
            return sources[reason]
        except KeyError as exc:
            raise ValueError(f"unknown attention reason: {reason!r}") from exc

    @staticmethod
    def _enrichment_join(c_scope: str, l_scope: str) -> str:
        """Lead-enrichment join condition for ``attention_rows``.

        For a conversation-anchored candidate (conversation_id not null), match
        the lead by the canonical ``leads.contact_id = conversations.contact_id``
        (Alembic 0047) via the candidate's conversation (pulled by id). For a
        lead-anchored candidate, match by ``leads.id = candidate.lead_id``
        directly. Viewer scope applies to the enrichment lead (``l_scope``)
        independently of the conversation scope; if the two disagree the
        candidate is dropped (no PII leak).
        """
        # cand.conversation_id is the deduped candidate's conversation; look up
        # its contact_id, then match leads by contact_id. Lead-anchored rows
        # fall back to id = lead_id.
        return (
            "WHERE (cand.conversation_id IS NOT NULL "
            "AND l.contact_id = (SELECT c2.contact_id FROM conversations c2 "
            "WHERE c2.id = cand.conversation_id) "
            "AND " + l_scope + ") "
            "OR (cand.conversation_id IS NULL AND cand.lead_id IS NOT NULL "
            "AND l.id = cand.lead_id AND " + l_scope + ")"
        )


__all__ = ["DashboardRepository"]
