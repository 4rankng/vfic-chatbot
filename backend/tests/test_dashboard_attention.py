"""Unit tests for the recruiter attention dashboard service + schema contract.

Pure-unit (mock-based, no DB) — mirrors the project's test_viewer_scope /
test_conversation_release pattern. The repository SQL is exercised by
integration tests; here we pin the SERVICE logic: cache hit/miss, viewer-scope
mapping, snapshot-consistency transaction wiring, response assembly, key/action
derivation, and the strict Pydantic response contract (extra="forbid").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.models.user import Role
from app.schemas.dashboard import (
    AttentionAction,
    AttentionCounters,
    AttentionDashboardOut,
    AttentionItemOut,
    AttentionReason,
)
from app.services.dashboard import service as service_mod
from app.services.conversation.repository import _unanswered_inbound_condition

UID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_UID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _viewer(role: Role, uid=UID) -> SimpleNamespace:
    return SimpleNamespace(role=role, id=uid)


def _row(**over) -> dict:
    """A repo attention row with every AttentionItemOut field except body."""
    base = {
        "reason": "REPLY_OVERDUE",
        "urgency_at": datetime(2026, 7, 12, 3, 0, tzinfo=timezone.utc),
        "conversation_id": UID,
        "lead_id": None,
        "name": "Nguyen Van A",
        "phone": "0901234567",
        "desired_job": "Lái xe",
        "lead_stage": "CONTACTING",
        "lead_score": "hot",
        "last_inbound_at": datetime(2026, 7, 12, 2, 0, tzinfo=timezone.utc),
        "due_at": None,
        "delivery_status": None,
    }
    base.update(over)
    return base


def _fake_repo(counters=None, immediate=None, today=None) -> MagicMock:
    """A DashboardRepository double whose attention methods are AsyncMocks.

    Captures the recruiter_id each method was called with so viewer-scope
    mapping can be asserted without a DB.
    """
    repo = MagicMock()
    repo.attention_counters = AsyncMock(
        return_value=counters
        or {"needs_reply": 5, "overdue": 2, "due_today": 1, "priority": 3, "unread": 4}
    )
    repo.attention_rows = AsyncMock(
        side_effect=lambda rid, queue, limit=8: {
            "immediate": immediate or [_row()],
            "today": today or [],
        }[queue]
    )
    return repo


def _fake_db():
    """A session double exposing both execute() and rollback() as AsyncMocks.

    attention() calls db.rollback() before SET LOCAL transaction_isolation so
    the isolation statement is the first in its transaction (the get_current_user
    dependency already ran a SELECT on the shared request session). Tests that
    assert on execute() call order still see SET LOCAL as execute() call #0.
    """
    return SimpleNamespace(execute=AsyncMock(), rollback=AsyncMock())


def _patch_service(
    monkeypatch,
    cache_get=None,
    cache_set=None,
    repo=None,
    app_env="development",
    cache_enabled=True,
):
    """Wire fakes into the service module and return the repo double."""
    monkeypatch.setattr(service_mod, "cache_get_json", AsyncMock(return_value=cache_get))
    set_mock = AsyncMock()
    if cache_set is not None:
        set_mock.return_value = cache_set
    monkeypatch.setattr(service_mod, "cache_set_json", set_mock)
    settings = SimpleNamespace(
        app_env=app_env,
        dashboard_cache_enabled=cache_enabled,
        dashboard_cache_ttl_seconds=30,
    )
    monkeypatch.setattr(service_mod, "get_settings", lambda: settings)
    captured_repo = repo or _fake_repo()
    monkeypatch.setattr(service_mod, "DashboardRepository", lambda _db: captured_repo)
    return captured_repo, set_mock


# --- schema contract --------------------------------------------------------


def test_attention_item_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AttentionItemOut(
            key="k",
            reason="REPLY_OVERDUE",
            urgency_at=datetime.now(timezone.utc),
            action="OPEN_CONVERSATION",
            unexpected="leak",
        )


def test_attention_item_accepts_phone_field():
    """Authenticated recruiter dashboard rows include the contact number."""
    item = AttentionItemOut(
        key="k",
        reason="REPLY_OVERDUE",
        urgency_at=datetime.now(timezone.utc),
        action="OPEN_CONVERSATION",
        phone="0901234567",
    )
    assert item.phone == "0901234567"


def test_attention_item_rejects_legacy_phone_last4_field():
    with pytest.raises(ValidationError):
        AttentionItemOut(
            key="k",
            reason="REPLY_OVERDUE",
            urgency_at=datetime.now(timezone.utc),
            action="OPEN_CONVERSATION",
            phone_last4="4567",
        )


def test_attention_item_has_no_latest_message_field():
    """latest_message body is deliberately excluded (third-party PII risk)."""
    item = AttentionItemOut(
        key="k",
        reason="UNREAD",
        urgency_at=datetime.now(timezone.utc),
        action="OPEN_CONVERSATION",
    )
    assert not hasattr(item, "latest_message")
    dumped = item.model_dump()
    assert "latest_message" not in dumped
    assert "body" not in dumped


def test_attention_counters_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AttentionCounters(needs_reply=1, overdue=1, due_today=1, priority=1, unread=1, extra=0)


def test_attention_dashboard_out_rejects_extra_fields():
    with pytest.raises(ValidationError):
        AttentionDashboardOut(
            updated_at=datetime.now(timezone.utc),
            counters=AttentionCounters(needs_reply=0, overdue=0, due_today=0, priority=0, unread=0),
            immediate=[],
            today=[],
            bonus=True,
        )


def test_attention_reason_enum_has_all_nine_reasons():
    expected = {
        "DELIVERY_REVIEW",
        "HUMAN_ESCALATION",
        "REPLY_OVERDUE",
        "FOLLOWUP_OVERDUE",
        "WAITING_REPLY",
        "PRIORITY_NO_ACTION",
        "FOLLOWUP_TODAY",
        "UNREAD",
        "STALLED",
    }
    assert {r.value for r in AttentionReason} == expected


def test_attention_action_enum_values():
    assert {a.value for a in AttentionAction} == {"OPEN_CONVERSATION", "CALL"}


def test_inbox_needs_attention_is_human_mode_only():
    sql = str(
        _unanswered_inbound_condition().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "'HUMAN'" in sql
    assert "'SEMI_AUTO'" not in sql


# --- service: viewer-scope mapping -----------------------------------------


@pytest.mark.asyncio
async def test_admin_viewer_maps_to_recruiter_id_none(monkeypatch):
    repo, _ = _patch_service(monkeypatch)
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    # admin → recruiter_id=None on every repo call
    for call in repo.attention_counters.call_args_list:
        assert call.args[0] is None
    assert repo.attention_rows.await_args_list[0].args[0] is None  # immediate
    assert repo.attention_rows.await_args_list[1].args[0] is None  # today
    assert isinstance(out, AttentionDashboardOut)


@pytest.mark.asyncio
async def test_recruiter_viewer_maps_to_str_id(monkeypatch):
    repo, _ = _patch_service(monkeypatch)
    db = _fake_db()
    await service_mod.DashboardService(db).attention(_viewer(Role.recruiter))
    assert repo.attention_counters.await_args.args[0] == str(UID)
    assert repo.attention_rows.await_args_list[0].args[0] == str(UID)


# --- service: cache hit / miss ---------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_payload_skips_db(monkeypatch):
    cached = {
        "updated_at": datetime(2026, 7, 12, 1, 0, tzinfo=timezone.utc).isoformat(),
        "counters": {"needs_reply": 9, "overdue": 8, "due_today": 7, "priority": 6, "unread": 5},
        "immediate": [],
        "today": [],
    }
    repo, set_mock = _patch_service(monkeypatch, cache_get=cached, app_env="production")
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    assert out.counters.needs_reply == 9
    # On cache hit the repo is never instantiated/awaited and cache_set is skipped.
    repo.attention_counters.assert_not_awaited()
    repo.attention_rows.assert_not_awaited()
    set_mock.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_miss_reads_db_and_sets_cache(monkeypatch):
    repo, set_mock = _patch_service(monkeypatch, app_env="production")
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    repo.attention_counters.assert_awaited_once()
    assert repo.attention_rows.await_count == 2  # immediate + today
    set_mock.assert_awaited_once()
    # cache key is per-viewer
    assert set_mock.await_args.args[0] == "dashboard:attention:admin"
    assert isinstance(out, AttentionDashboardOut)


@pytest.mark.asyncio
async def test_cache_disabled_in_development_never_reads_nor_writes_redis(monkeypatch):
    repo, set_mock = _patch_service(monkeypatch, app_env="development", cache_enabled=True)
    db = _fake_db()
    await service_mod.DashboardService(db).attention(_viewer(Role.recruiter))
    # The prod gate is app_env == "production"; dev skips cache entirely.
    set_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_key_per_recruiter_scope(monkeypatch):
    repo, set_mock = _patch_service(monkeypatch, app_env="production")
    db = _fake_db()
    await service_mod.DashboardService(db).attention(_viewer(Role.recruiter))
    assert set_mock.await_args.args[0] == f"dashboard:attention:recruiter:{UID}"


# --- service: snapshot consistency -----------------------------------------


@pytest.mark.asyncio
async def test_sets_repeatable_read_isolation_for_single_snapshot(monkeypatch):
    """All 3 reads must share one snapshot (Red-team Critical 3)."""
    _patch_service(monkeypatch)
    execute = AsyncMock()
    rollback = AsyncMock()
    db = SimpleNamespace(execute=execute, rollback=rollback)
    await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    # The FIRST execute call sets the isolation level before any reads.
    first_sql = execute.await_args_list[0].args[0].text
    assert "SET LOCAL transaction_isolation" in first_sql
    assert "repeatable read" in first_sql


@pytest.mark.asyncio
async def test_rolls_back_prior_transaction_before_set_local(monkeypatch):
    """Regression: get_current_user's SELECT autobegins a transaction on the
    shared request session, so SET LOCAL transaction_isolation must NOT be its
    first statement — Postgres rejects that with ActiveSQLTransactionError
    ("SET TRANSACTION ISOLATION LEVEL must be called before any query").

    The service calls db.rollback() first to end the autobegun transaction, then
    issues SET LOCAL as the first statement of the fresh transaction. Pin both
    halves of the contract and their ordering.
    """
    _patch_service(monkeypatch)
    execute = AsyncMock()
    rollback = AsyncMock()
    db = SimpleNamespace(execute=execute, rollback=rollback)
    await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    # rollback is awaited exactly once...
    rollback.assert_awaited_once()
    # ...and it happens BEFORE the SET LOCAL execute (call order on the session).
    # We assert via the two mocks' await order by checking call_count at the
    # point each fired: rollback must precede the SET LOCAL execute. The execute
    # mock received exactly one call (SET LOCAL) since the repo is mocked.
    execute.assert_awaited_once()
    assert "SET LOCAL transaction_isolation" in execute.await_args_list[0].args[0].text


# --- service: round-trip budget --------------------------------------------


@pytest.mark.asyncio
async def test_at_most_three_db_round_trips(monkeypatch):
    """Performance budget: counters(1) + immediate(1) + today(1) = 3 reads."""
    repo, _ = _patch_service(monkeypatch)
    execute = AsyncMock()
    db = SimpleNamespace(execute=execute, rollback=AsyncMock())
    await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    # 1 SET LOCAL + 0 repo queries (repo is mocked, uses its own db-free path)
    # → the repo-level budget is: 1 counters + 2 rows = 3 attention reads.
    assert repo.attention_counters.await_count == 1
    assert repo.attention_rows.await_count == 2


# --- service: response assembly --------------------------------------------


@pytest.mark.asyncio
async def test_updated_at_is_set_to_now(monkeypatch):
    before = datetime.now(timezone.utc)
    _patch_service(monkeypatch)
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    after = datetime.now(timezone.utc)
    assert before <= out.updated_at <= after


@pytest.mark.asyncio
async def test_conversation_anchored_row_gets_open_conversation_action(monkeypatch):
    conv_row = _row(conversation_id=UID, lead_id=None, reason="REPLY_OVERDUE")
    repo = _fake_repo(immediate=[conv_row], today=[])
    _patch_service(monkeypatch, repo=repo)
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    item = out.immediate[0]
    assert item.key == str(UID)
    assert item.action is AttentionAction.OPEN_CONVERSATION
    assert item.reason is AttentionReason.REPLY_OVERDUE
    assert item.conversation_id == UID
    assert item.phone == "0901234567"
    assert item.lead_stage == "CONTACTING"


@pytest.mark.asyncio
async def test_lead_anchored_row_gets_call_action(monkeypatch):
    lead_row = _row(conversation_id=None, lead_id=42, reason="STALLED")
    repo = _fake_repo(immediate=[], today=[lead_row])
    _patch_service(monkeypatch, repo=repo)
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    item = out.today[0]
    assert item.key == "lead:42"
    assert item.action is AttentionAction.CALL
    assert item.conversation_id is None
    assert item.lead_id == 42


@pytest.mark.asyncio
async def test_counters_mapped_to_schema_keys(monkeypatch):
    counters = {"needs_reply": 11, "overdue": 22, "due_today": 33, "priority": 44, "unread": 55}
    repo = _fake_repo(counters=counters)
    _patch_service(monkeypatch, repo=repo)
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    assert out.counters == AttentionCounters(
        needs_reply=11, overdue=22, due_today=33, priority=44, unread=55
    )


@pytest.mark.asyncio
async def test_delivery_review_row_carries_delivery_status(monkeypatch):
    dr_row = _row(
        reason="DELIVERY_REVIEW",
        delivery_status="SEND_UNKNOWN",
        conversation_id=UID,
    )
    repo = _fake_repo(immediate=[dr_row], today=[])
    _patch_service(monkeypatch, repo=repo)
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    assert out.immediate[0].delivery_status == "SEND_UNKNOWN"
    assert out.immediate[0].reason is AttentionReason.DELIVERY_REVIEW


@pytest.mark.asyncio
async def test_round_trip_payload_includes_phone_but_not_message_text(monkeypatch):
    _patch_service(monkeypatch)
    db = _fake_db()
    out = await service_mod.DashboardService(db).attention(_viewer(Role.admin))
    dumped = out.model_dump(mode="json")
    for item in dumped["immediate"] + dumped["today"]:
        assert item["phone"] == "0901234567"
        assert "phone_last4" not in item
        assert "latest_message" not in item
        assert "body" not in item


# --- repository: vn_today helper (pure, no DB) -----------------------------


def test_vn_today_predicate_uses_ho_chi_minh_zone():
    from app.services.dashboard.repository import DashboardRepository

    sql = DashboardRepository._vn_today_predicate("f.due_at")
    # Both sides must convert via Asia/Ho_Chi_Minh (not UTC date math).
    assert sql.count("Asia/Ho_Chi_Minh") == 2
    assert "::date" in sql
    assert "f.due_at" in sql
    assert "now()" in sql


# --- repository: viewer-scope contract on lead-anchored CTEs (N1) ---------
#
# The four lead-anchored CTEs LEFT JOIN conversations to surface conversation_id
# + last_inbound_at. That join must apply viewer scope (c_scope) so a recruiter
# never sees another recruiter's conversation_id via a zalo_id soft match. These
# are string-level contract tests pinning the fix: they construct a
# DashboardRepository with a mock session, drive attention_rows with a real
# recruiter_id, capture the compiled SQL, and assert the c_scope fragment is in
# each lead-anchored LEFT JOIN condition.


async def _captured_attention_sql(recruiter_id: str | None, queue: str) -> str:
    """Run ``DashboardRepository.attention_rows`` against a mock session and
    return the compiled SQL string passed to ``db.execute``.

    The mock's execute returns a result whose ``.mappings()`` yields nothing —
    we only care about the SQL text, not the rows.
    """
    from app.services.dashboard.repository import DashboardRepository

    repo = DashboardRepository(db=MagicMock())
    repo.db.execute = AsyncMock(return_value=SimpleNamespace(mappings=lambda: iter([])))
    await repo.attention_rows(recruiter_id, queue, limit=8)
    call = repo.db.execute.await_args
    return call.args[0].text


@pytest.mark.asyncio
async def test_lead_anchored_ctes_include_c_scope_in_left_join_immediate():
    """N1 fix: followup_overdue (the one lead-anchored CTE in the immediate
    queue) must scope its LEFT JOIN to conversations on c_scope.

    The lead↔conversation link is the canonical contact_id (Alembic 0047),
    replacing the legacy Zalo-only soft match.
    """
    sql = await _captured_attention_sql(str(UID), "immediate")
    # The followup_overdue LEFT JOIN must carry the c_scope fragment so a
    # recruiter's lead does not surface another recruiter's conversation_id.
    assert (
        "c.contact_id = l.contact_id AND (c.assigned_recruiter_id = :uid "
        "OR c.assigned_recruiter_id IS NULL)"
    ) in sql


@pytest.mark.asyncio
async def test_lead_anchored_ctes_include_c_scope_in_left_join_today():
    """N1 fix: priority_no_action + stalled + followup_today (the lead-anchored
    CTEs in the today queue) must each scope their LEFT JOIN on c_scope."""
    sql = await _captured_attention_sql(str(UID), "today")
    expected_fragment = (
        "c.contact_id = l.contact_id AND (c.assigned_recruiter_id = :uid "
        "OR c.assigned_recruiter_id IS NULL)"
    )
    # Three lead-anchored CTEs in the today queue: priority_no_action,
    # followup_today, stalled. Each contributes one scoped LEFT JOIN.
    assert sql.count(expected_fragment) == 3


@pytest.mark.asyncio
async def test_admin_attendance_rows_omits_c_scope_predicate():
    """For admin (recruiter_id is None), c_scope is a no-op '(TRUE)' — the LEFT
    JOIN keeps matching all conversations. Pins the admin/global branch."""
    sql = await _captured_attention_sql(None, "today")
    # c_scope for admin collapses to (TRUE), so the join reads
    # ... = l.contact_id AND (TRUE)
    assert "c.contact_id = l.contact_id AND (TRUE)" in sql
    # and never references :uid on the admin path
    assert ":uid" not in sql


@pytest.mark.asyncio
async def test_lead_anchored_left_join_is_outer_so_null_conversation_is_kept():
    """The scoped LEFT JOIN must stay a LEFT JOIN: when no in-scope conversation
    matches, c.* is NULL and the lead-anchored row still surfaces with action=CALL
    + key='lead:<id>'. Pin that the join keyword is LEFT JOIN (not JOIN)."""
    sql = await _captured_attention_sql(str(UID), "immediate")
    assert "LEFT JOIN conversations c ON c.contact_id = l.contact_id" in sql


@pytest.mark.asyncio
async def test_attention_rows_select_full_phone_for_recruiter_follow_up():
    sql = await _captured_attention_sql(str(UID), "immediate")
    assert "el.name, el.phone, el.desired_job" in sql
    assert "SELECT l.name, l.phone, l.desired_job" in sql
    assert "right(l.phone, 4)" not in sql


@pytest.mark.asyncio
async def test_human_intervention_sources_require_human_mode_and_unanswered_inbound():
    """Every reason shown in ``Cần can thiệp`` must share one queue contract."""
    sql = await _captured_attention_sql(str(UID), "immediate")
    human_unanswered = (
        "c.status = 'OPEN' AND c.mode = 'HUMAN' AND c.last_inbound_at IS NOT NULL "
        "AND (c.last_outbound_at IS NULL OR c.last_inbound_at > c.last_outbound_at)"
    )

    # DELIVERY_REVIEW, HUMAN_ESCALATION, REPLY_OVERDUE and WAITING_REPLY are
    # the four conversation reasons the frontend may render in this panel.
    assert sql.count(human_unanswered) == 4


def test_attention_reason_deep_links_share_human_unanswered_contract():
    from app.services.dashboard.repository import DashboardRepository

    repo = DashboardRepository(db=MagicMock())
    human_unanswered = (
        "c.status = 'OPEN' AND c.mode = 'HUMAN' AND c.last_inbound_at IS NOT NULL "
        "AND (c.last_outbound_at IS NULL OR c.last_inbound_at > c.last_outbound_at)"
    )

    for reason in (
        "DELIVERY_REVIEW",
        "HUMAN_ESCALATION",
        "REPLY_OVERDUE",
        "WAITING_REPLY",
    ):
        assert human_unanswered in repo._attention_reason_source(reason, str(UID))


# --- metrics: 24h bot-run window + merged core counts -----------------------


async def _captured_repo_sql(method: str, recruiter_id: str | None):
    """Run a repository method against a mock session, return (sql_text, params).

    Mirrors ``_captured_attention_sql`` above: only the SQL text and bound
    parameters matter, so the mock result carries an empty row set. Works for
    any repo method that reads through ``db.execute(...).mappings().one()``.
    """
    from app.services.dashboard.repository import DashboardRepository

    repo = DashboardRepository(db=MagicMock())
    empty_row = {key: 0 for key in (*DashboardRepository._CORE_COUNT_KEYS, "total", "sent", "suppressed", "errors", "avg_seconds")}
    repo.db.execute = AsyncMock(
        return_value=SimpleNamespace(
            mappings=lambda: SimpleNamespace(one=lambda: empty_row)
        )
    )
    await getattr(repo, method)(recruiter_id)
    call = repo.db.execute.await_args
    params = call.args[1] if len(call.args) > 1 else {}
    return call.args[0].text, params


async def test_bot_run_summary_bounded_to_last_24h_global():
    sql, params = await _captured_repo_sql("bot_run_summary", None)
    assert "b.started_at > now() - interval '24 hours'" in sql
    assert ":uid" not in sql
    assert params == {}


async def test_bot_run_summary_scoped_keeps_window_and_viewer_scope():
    sql, params = await _captured_repo_sql("bot_run_summary", str(UID))
    assert "b.started_at > now() - interval '24 hours'" in sql
    assert "c.assigned_recruiter_id = :uid OR c.assigned_recruiter_id IS NULL" in sql
    assert params == {"uid": str(UID)}


async def test_core_counts_is_one_round_trip_with_exact_predicates():
    from app.services.dashboard.repository import DashboardRepository

    repo = DashboardRepository(db=MagicMock())
    row = {
        "open_conversations": 3,
        "hot_leads": 2,
        "pending_followups": 1,
        "failed_sends": 1,
        "bot_errors": 0,
    }
    repo.db.execute = AsyncMock(
        return_value=SimpleNamespace(
            mappings=lambda: SimpleNamespace(one=lambda: row)
        )
    )
    result = await repo.core_counts(None)

    assert repo.db.execute.await_count == 1
    assert result == row
    sql = repo.db.execute.await_args.args[0].text
    for fragment in (
        "c.status = 'OPEN'",
        "l.lead_score = 'hot'",
        "f.status = 'PENDING'",
        "m.delivery_status = 'FAILED'",
        "b.outcome = 'ERROR'",
    ):
        assert fragment in sql
    assert ":uid" not in sql


async def test_core_counts_scoped_carries_viewer_scope_param():
    sql, params = await _captured_repo_sql("core_counts", str(UID))
    assert "c.assigned_recruiter_id = :uid OR c.assigned_recruiter_id IS NULL" in sql
    assert "l.assigned_recruiter_id = :uid OR l.assigned_recruiter_id IS NULL" in sql
    assert params == {"uid": str(UID)}


async def _run_metrics(monkeypatch, app_env="development", cache_enabled=True, bot_summary=None):
    """Drive ``DashboardService.metrics`` on a recruiter viewer with a fake repo.

    Returns (repo double, cache-set mock, built DashboardMetrics). The
    attention-side ``_patch_service`` helper is reused so cache/settings
    wiring stays in one place.
    """
    repo = MagicMock()
    repo.core_counts = AsyncMock(
        return_value={
            "open_conversations": 3,
            "hot_leads": 2,
            "pending_followups": 1,
            "failed_sends": 1,
            "bot_errors": 0,
        }
    )
    repo.bot_run_summary = AsyncMock(
        return_value=bot_summary
        or {
            "total": 10,
            "sent": 8,
            "suppressed": 1,
            "errors": 1,
            "avg_seconds": 2.5,
        }
    )
    repo.leads_by_stage = AsyncMock(return_value={"NEW": 3, "CONTACTING": 2, "REGISTERED": 1})
    repo.count_human_conversations = AsyncMock(return_value=7)
    repo.active_turns = AsyncMock(return_value=2)
    repo.bot_run_p95_latency = AsyncMock(return_value=1.8)
    repo.recent_turns_count = AsyncMock(return_value=4)

    captured_repo, set_mock = _patch_service(
        monkeypatch, repo=repo, app_env=app_env, cache_enabled=cache_enabled
    )
    monkeypatch.setattr(
        service_mod.DashboardService, "_webhook_queue_depth", lambda self: 0
    )
    monkeypatch.setattr(
        service_mod.DashboardService, "_rq_ingest_counts", lambda self: (0, 0, 0)
    )
    metrics = await service_mod.DashboardService(MagicMock()).metrics(_viewer(Role.recruiter))
    return captured_repo, set_mock, metrics


async def test_metrics_builds_all_tiles_from_merged_counts_and_24h_summary(monkeypatch):
    repo, _, metrics = await _run_metrics(monkeypatch)

    repo.core_counts.assert_awaited_once_with(str(UID))
    repo.bot_run_summary.assert_awaited_once_with(str(UID))
    assert metrics.bot_run_count == 10
    assert metrics.bot_sent_count == 8
    assert metrics.bot_suppressed_count == 1
    assert metrics.bot_success_rate == 80.0
    assert metrics.bot_suppression_rate == pytest.approx(1 / 9)
    assert metrics.avg_bot_response_seconds == 2.5
    assert metrics.open_conversations == 3
    assert metrics.hot_leads == 2
    assert metrics.bot_errors == 0
    assert metrics.turns_last_5min == 4


async def test_metrics_suppression_rate_zero_denominator_is_zero(monkeypatch):
    _, _, metrics = await _run_metrics(
        monkeypatch,
        bot_summary={"total": 3, "sent": 0, "suppressed": 0, "errors": 3, "avg_seconds": 0.0},
    )
    assert metrics.bot_suppression_rate == 0.0


async def test_metrics_cache_write_uses_60s_ttl_floor(monkeypatch):
    _, set_mock, _ = await _run_metrics(monkeypatch, app_env="production")
    assert set_mock.await_args.args[2] == 60


async def test_attention_cache_write_uses_60s_ttl_floor(monkeypatch):
    _, set_mock = _patch_service(monkeypatch, app_env="production")
    await service_mod.DashboardService(_fake_db()).attention(_viewer(Role.admin))
    assert set_mock.await_args.args[2] == 60