"""Data-access layer for dashboard metrics.

Verbatim ports of the count / funnel / ingest-health queries DashboardService
previously ran inline, so the service owns only viewer-scoping + result assembly
(business logic) and the Redis telemetry call.

Each metric branches on ``recruiter_id``: ``None`` = global (admin), a uid = scoped
to that recruiter's assigned-or-unassigned rows. The "admin = global, recruiter =
assigned" rule is decided by the SERVICE and passed in; this repo just runs the SQL.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.viewer_scope import viewer_scope_sql


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

    async def count_open_conversations(self, recruiter_id: str | None = None) -> int | None:
        return await self._scoped_scalar(
            recruiter_id,
            "SELECT count(*) FROM conversations WHERE status = 'OPEN'",
            "SELECT count(*) FROM conversations c "
            "WHERE c.status = 'OPEN' "
            "AND " + viewer_scope_sql("c."),
        )

    async def count_hot_leads(self, recruiter_id: str | None = None) -> int | None:
        return await self._scoped_scalar(
            recruiter_id,
            "SELECT count(*) FROM leads WHERE lead_score = 'hot'",
            "SELECT count(*) FROM leads l WHERE l.lead_score = 'hot' AND " + viewer_scope_sql("l."),
        )

    async def count_pending_followups(self, recruiter_id: str | None = None) -> int | None:
        return await self._scoped_scalar(
            recruiter_id,
            "SELECT count(*) FROM follow_up_tasks WHERE status = 'PENDING'",
            "SELECT count(*) FROM follow_up_tasks f JOIN leads l ON l.id = f.lead_id "
            "WHERE f.status = 'PENDING' "
            "AND " + viewer_scope_sql("l."),
        )

    async def count_failed_sends(self, recruiter_id: str | None = None) -> int | None:
        return await self._scoped_scalar(
            recruiter_id,
            "SELECT count(*) FROM messages WHERE delivery_status = 'FAILED'",
            "SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.delivery_status = 'FAILED' "
            "AND " + viewer_scope_sql("c."),
        )

    async def count_bot_errors(self, recruiter_id: str | None = None) -> int | None:
        return await self._scoped_scalar(
            recruiter_id,
            "SELECT count(*) FROM bot_runs WHERE outcome = 'ERROR'",
            "SELECT count(*) FROM bot_runs b JOIN conversations c ON c.id = b.conversation_id "
            "WHERE b.outcome = 'ERROR' "
            "AND " + viewer_scope_sql("c."),
        )

    async def bot_run_summary(self, recruiter_id: str | None = None) -> dict[str, float | int]:
        """Aggregate bot-turn health without downloading the bot_run audit log."""
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
            sql += " JOIN conversations c ON c.id = b.conversation_id WHERE " + viewer_scope_sql(
                "c."
            )
            params["uid"] = recruiter_id
        row = (await self.db.execute(text(sql), params)).mappings().one()
        return {
            "total": int(row["total"] or 0),
            "sent": int(row["sent"] or 0),
            "suppressed": int(row["suppressed"] or 0),
            "errors": int(row["errors"] or 0),
            "avg_seconds": float(row["avg_seconds"] or 0.0),
        }

    async def bot_suppression_rate(self, recruiter_id: str | None = None) -> float | None:
        return await self._scoped_scalar(
            recruiter_id,
            "SELECT count(*) FILTER (WHERE outcome='SUPPRESSED')::float / NULLIF(count(*),0) AS rate "
            "FROM bot_runs WHERE outcome IN ('SENT','SUPPRESSED')",
            "SELECT count(*) FILTER (WHERE b.outcome='SUPPRESSED')::float / NULLIF(count(*),0) AS rate "
            "FROM bot_runs b JOIN conversations c ON c.id = b.conversation_id "
            "WHERE b.outcome IN ('SENT','SUPPRESSED') "
            "AND " + viewer_scope_sql("c."),
        )

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
                        "WHERE " + viewer_scope_sql("") + " "
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
            "SELECT count(*) FROM conversations WHERE mode = 'HUMAN' AND " + viewer_scope_sql(""),
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
        c_scope = viewer_scope_sql("c.") if recruiter_id is not None else "(TRUE)"
        l_scope = viewer_scope_sql("l.") if recruiter_id is not None else "(TRUE)"
        params: dict[str, str] = {}
        if recruiter_id is not None:
            params["uid"] = recruiter_id

        vn_today_due = self._vn_today_predicate("f.due_at")

        # --- Conversation-anchored predicates (viewer scope on c.) -----------
        # HUMAN_ESCALATION: open conversation flagged needs_human.
        human_esc = (
            "SELECT count(*) FROM conversations c "
            "WHERE c.status = 'OPEN' AND c.needs_human AND " + c_scope
        )
        # REPLY_OVERDUE: unanswered inbound age >= 30 minutes.
        reply_overdue = (
            "SELECT count(*) FROM conversations c "
            "WHERE c.status = 'OPEN' "
            "AND c.last_inbound_at IS NOT NULL "
            "AND c.last_inbound_at > c.last_outbound_at "
            "AND c.last_inbound_at < now() - interval '30 minutes' "
            "AND " + c_scope
        )
        # WAITING_REPLY: unanswered inbound age < 30 minutes (still in grace).
        waiting_reply = (
            "SELECT count(*) FROM conversations c "
            "WHERE c.status = 'OPEN' "
            "AND c.last_inbound_at IS NOT NULL "
            "AND c.last_inbound_at > c.last_outbound_at "
            "AND c.last_inbound_at >= now() - interval '30 minutes' "
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
            "AND " + c_scope
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
            f"({human_esc}) + ({reply_overdue}) + ({waiting_reply}) AS needs_reply, "
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

        c_scope = viewer_scope_sql("c.") if recruiter_id is not None else "(TRUE)"
        l_scope = viewer_scope_sql("l.") if recruiter_id is not None else "(TRUE)"
        params: dict[str, object] = {"limit": limit}
        if recruiter_id is not None:
            params["uid"] = recruiter_id
        vn_today_due = self._vn_today_predicate("f.due_at")
        not_skipped = "l.lead_stage <> 'SKIPPED'"

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
            "  WHERE m.delivery_status IN ('FAILED','SEND_UNKNOWN') AND " + c_scope + ")"
        )
        human_esc_cte = (
            "human_escalation AS ("
            "  SELECT c.id AS conversation_id, NULL::bigint AS lead_id, "
            "  'HUMAN_ESCALATION'::text AS reason, 2 AS precedence, "
            "  coalesce(c.last_inbound_at, c.updated_at) AS urgency_at, "
            "  NULL::text AS delivery_status, c.last_inbound_at, "
            "  NULL::timestamptz AS due_at "
            "  FROM conversations c "
            "  WHERE c.status = 'OPEN' AND c.needs_human AND " + c_scope + ")"
        )
        reply_overdue_cte = (
            "reply_overdue AS ("
            "  SELECT c.id AS conversation_id, NULL::bigint AS lead_id, "
            "  'REPLY_OVERDUE'::text AS reason, 3 AS precedence, "
            "  c.last_inbound_at AS urgency_at, NULL::text AS delivery_status, "
            "  c.last_inbound_at, NULL::timestamptz AS due_at "
            "  FROM conversations c "
            "  WHERE c.status = 'OPEN' AND c.last_inbound_at IS NOT NULL "
            "  AND c.last_inbound_at > c.last_outbound_at "
            "  AND c.last_inbound_at < now() - interval '30 minutes' AND " + c_scope + ")"
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
            "  WHERE c.status = 'OPEN' AND c.last_inbound_at IS NOT NULL "
            "  AND c.last_inbound_at > c.last_outbound_at "
            "  AND c.last_inbound_at >= now() - interval '30 minutes' AND " + c_scope + ")"
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
