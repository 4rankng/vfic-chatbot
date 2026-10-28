"""Cloudfone service: GetCallHistoryVer2 legs → call clustering → daily stats,
STT wiring, insights build, and the pass.

The client's transport is injected (``httpx.MockTransport``), the fetcher,
transcriber, summarizer and sender are callables — no network and no graph
import anywhere here. The 14-leg day fixture is the vendor's real
2026-10-01 row shape (verified live); linkFile tokens are shortened to
structurally-identical placeholders.
"""

# pyright: reportArgumentType=false

import json
from dataclasses import replace
from datetime import date, datetime, timezone

import httpx
import pytest

import app.services.cloudfone as cloudfone_module
from app.services.email_service import EmailDeliveryError
from app.services.integration_settings import (
    CloudfoneRuntimeConfig,
    EmailDigestRuntimeConfig,
    MinimaxRuntimeConfig,
)
from app.services.cloudfone import (
    STATUS_DISABLED,
    STATUS_EMPTY,
    STATUS_SENT,
    STATUS_UNCONFIGURED,
    CallRecord,
    CloudfoneClient,
    CloudfoneError,
    DailyCallStats,
    build_daily_insights,
    build_daily_stats,
    build_insights,
    call_date_to_ict,
    group_call_legs,
    insights_subject,
    insights_window,
    render_insights_html,
    run_cloudfone_insights,
)


def _envelope(items: list[dict], *, total: int | None = None) -> dict:
    """The live success envelope: result/message/total/data(list)."""
    return {
        "result": "success",
        "message": "",
        "total": len(items) if total is None else total,
        "data": items,
    }


def _leg(
    call_date: str,
    key: str,
    caller: str,
    receive: str,
    status: str,
    real: int | str,
    *,
    link: str = "",
    caller_name: str = "",
    total: int | str = 0,
    direction: str = "Inbound",
) -> dict:
    """One GetCallHistoryVer2 leg row in the verified live shape."""
    return {
        "stt": 0,
        "key": key,
        "callDate": call_date,
        "callerNumber": caller,
        "callerName": caller_name or caller,
        "headNumber": "18007228",
        "receiveNumber": receive,
        "status": status,
        "totalCallTime": str(total),
        "realCallTime": str(real),
        "linkFile": link,
        "gsmPort": "",
        "typecall": direction,
    }


# The vendor's real 2026-10-01 day: 14 legs → 7 calls (4 answered, 3 missed).
_REAL_LINK_A = "https://90.cloudfone.vn/Home?ID=rec-0750"
REAL_DAY_LEGS = [
    # 07:50 call — queue + agent leg + hangup leg claiming ANSWERED/0.
    _leg("2026-10-01T07:50:24", "1790815824.562-104", "0364489026", "104", "NO ANSWER", 0),
    _leg(
        "2026-10-01T07:50:24",
        "1790815824.560-3000(Nhóm)",
        "0364489026",
        "3000(Nhóm)",
        "NO ANSWER",
        20,
        link=_REAL_LINK_A,
        total=20,
    ),
    _leg(
        "2026-10-01T07:50:44",
        "1790815824.560-hangup",
        "0364489026",
        "hangup",
        "ANSWERED",
        0,
        link=_REAL_LINK_A,
    ),
    # 07:58 redial — 445s later: its own call.
    _leg(
        "2026-10-01T07:58:09",
        "1790816289.564-3000(Nhóm)",
        "0364489026",
        "3000(Nhóm)",
        "NO ANSWER",
        1,
        link="https://90.cloudfone.vn/Home?ID=rec-0758",
        total=1,
    ),
    # 08:35 transfer — legs 1s apart share one call.
    _leg(
        "2026-10-01T08:35:23",
        "1790818523.568-2000(Nhóm)",
        "0364489026",
        "2000(Nhóm)",
        "ANSWERED",
        103,
        link="https://90.cloudfone.vn/Home?ID=rec-0835",
        total=103,
    ),
    _leg(
        "2026-10-01T08:35:24",
        "1790818524.570-101",
        "0364489026",
        "101",
        "ANSWERED",
        98,
        link="https://90.cloudfone.vn/Home?ID=rec-0835",
        total=103,
    ),
    # 14:23 transfer.
    _leg(
        "2026-10-01T14:23:15",
        "1790839395.572-2000(Nhóm)",
        "0362172696",
        "2000(Nhóm)",
        "ANSWERED",
        72,
        link="https://90.cloudfone.vn/Home?ID=rec-1423",
        total=72,
    ),
    _leg(
        "2026-10-01T14:23:15",
        "1790839395.574-101",
        "0362172696",
        "101",
        "ANSWERED",
        61,
        link="https://90.cloudfone.vn/Home?ID=rec-1423",
        total=71,
    ),
    # 16:37 transfer.
    _leg(
        "2026-10-01T16:37:50",
        "1790847470.576-2000(Nhóm)",
        "0362698948",
        "2000(Nhóm)",
        "ANSWERED",
        76,
        link="https://90.cloudfone.vn/Home?ID=rec-1637",
        total=76,
    ),
    _leg(
        "2026-10-01T16:37:51",
        "1790847470.578-102",
        "0362698948",
        "102",
        "ANSWERED",
        72,
        link="https://90.cloudfone.vn/Home?ID=rec-1637",
        total=76,
    ),
    # 16:41 missed — second caller of the day.
    _leg(
        "2026-10-01T16:41:17",
        "1790847677.580-2000(Nhóm)",
        "0902065233",
        "2000(Nhóm)",
        "NO ANSWER",
        4,
        link="https://90.cloudfone.vn/Home?ID=rec-1641",
        total=4,
    ),
    _leg("2026-10-01T16:41:18", "1790847678.582-101", "0902065233", "101", "NO ANSWER", 0, total=4),
    # 17:02 transfer — same caller as 16:37, 25min later: its own call.
    _leg(
        "2026-10-01T17:02:35",
        "1790848955.584-2000(Nhóm)",
        "0362698948",
        "2000(Nhóm)",
        "ANSWERED",
        101,
        link="https://90.cloudfone.vn/Home?ID=rec-1702",
        total=101,
    ),
    _leg(
        "2026-10-01T17:02:35",
        "1790848955.586-102",
        "0362698948",
        "102",
        "ANSWERED",
        98,
        link="https://90.cloudfone.vn/Home?ID=rec-1702",
        total=101,
    ),
]


def _transport_client(handler) -> CloudfoneClient:
    """A client whose HTTP call rides an httpx.MockTransport (no sockets)."""
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.cloudfone.vn/api/CloudFone",
    )

    async def transport(method: str, body: dict) -> dict:
        response = await http.post(f"/{method}", json=body)
        if response.status_code >= 400:
            raise CloudfoneError(f"CloudFone trả lỗi HTTP {response.status_code}")
        return response.json()

    return CloudfoneClient("CloudFone", "cloudfone-user", "cf-key", transport=transport)


async def test_get_call_history_v2_sends_the_vendor_postman_body():
    """Auth trio + the Postman body fields verbatim; PageIndex 1-based here."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope([]))

    rows = await _transport_client(handler).get_call_history_v2(
        day=date(2026, 10, 1), page_index=1, page_size=5
    )

    assert rows == []
    assert seen["url"].endswith("/GetCallHistoryVer2")
    assert seen["body"] == {
        "ServiceName": "CloudFone",
        "AuthUser": "cloudfone-user",
        "AuthKey": "cf-key",
        "TypeGet": 0,
        "HideFWOut": 1,
        "DateStart": "2026-10-01 00:00:00",
        "DateEnd": "2026-10-01 23:59:59",
        "IsSort": 0,
        "CallNum": "",
        "ReceiveNum": "",
        "Key": "",
        "PageIndex": 1,
        "PageSize": 5,
    }
    # The key must never ride the query string (proxy logs stay clean).
    assert "cf-key" not in seen["url"]


async def test_client_rejects_a_non_success_result():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "error", "message": "Invalid APIKey"})

    with pytest.raises(CloudfoneError, match="Invalid APIKey"):
        await _transport_client(handler).get_call_history_v2(day=date(2026, 10, 1))


async def test_client_rejects_the_live_failure_envelope():
    """The verified live shape: HTTP 200, result=failure, empty message."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"result": "failure", "message": "", "total": 0, "data": None}
        )

    with pytest.raises(CloudfoneError, match="không rõ lý do"):
        await _transport_client(handler).get_call_history_v2(day=date(2026, 10, 1))


async def test_group_call_legs_merges_transfer_legs_into_one_call():
    """Legs 1s apart (queue → agent) are one dial attempt: one call record."""
    calls = group_call_legs(REAL_DAY_LEGS[4:6])
    assert len(calls) == 1
    call = calls[0]
    assert call.call_id == "1790818523"  # epoch before the "." of the first leg's key
    assert call.started_at == "2026-10-01T08:35:23"
    assert call.caller == "0364489026"
    assert call.direction == "Inbound"
    assert call.status == "ANSWERED"
    assert call.talk_seconds == 103  # max realCallTime over answered legs
    assert call.agent == "2000(Nhóm)"  # the answered leg with max realCallTime
    assert call.recording_url == "https://90.cloudfone.vn/Home?ID=rec-0835"


async def test_group_call_legs_hangup_leg_never_counts_answered():
    """…-hangup legs claim ANSWERED/0 — the call is missed, not answered."""
    calls = group_call_legs(REAL_DAY_LEGS[0:3])
    assert len(calls) == 1
    call = calls[0]
    assert call.status == "NO ANSWER"
    assert call.talk_seconds == 0
    assert call.recording_url == "https://90.cloudfone.vn/Home?ID=rec-0750"


async def test_group_call_legs_splits_redials_at_the_30s_boundary():
    """Same caller 35s apart = two dial attempts = two calls."""
    first = _leg(
        "2026-10-01T13:25:02",
        "1791181502.600-2000(Nhóm)",
        "0901234567",
        "2000(Nhóm)",
        "NO ANSWER",
        0,
    )
    second = _leg(
        "2026-10-01T13:25:37",
        "1791181537.602-2000(Nhóm)",
        "0901234567",
        "2000(Nhóm)",
        "NO ANSWER",
        0,
    )
    calls = group_call_legs([first, second])
    assert [call.call_id for call in calls] == ["1791181502", "1791181537"]
    assert [call.started_at for call in calls] == ["2026-10-01T13:25:02", "2026-10-01T13:25:37"]


async def test_group_call_legs_zero_second_pickup_is_not_answered():
    """An ANSWERED leg with 0s talk produced no conversation — not answered."""
    calls = group_call_legs(
        [_leg("2026-10-01T09:00:00", "1791200000.610-101", "0901234567", "101", "ANSWERED", 0)]
    )
    assert len(calls) == 1
    assert calls[0].status != "ANSWERED"
    assert calls[0].talk_seconds == 0
    assert build_daily_stats(calls).missed == (("2026-10-01T09:00:00", "0901234567"),)


def test_call_date_to_ict_keeps_naive_vendor_ict_unchanged():
    """Vendor callDate is already Vietnam wall clock (verified live via the key
    epoch) — the string passes through without a shift."""
    assert call_date_to_ict("2026-10-24T07:37:37") == "2026-10-24T07:37:37"


def test_call_date_to_ict_keeps_aware_offset_and_garbage():
    """Aware timestamps convert by their own offset; garbage passes through."""
    assert call_date_to_ict("2026-10-24T07:37:37+00:00") == "2026-10-24T14:37:37"
    assert call_date_to_ict("2026-10-24T07:37:37+07:00") == "2026-10-24T07:37:37"
    assert call_date_to_ict("not-a-date") == "not-a-date"
    assert call_date_to_ict("") == ""


def test_day_window_covers_the_full_ict_day_in_the_vendor_ict_clock():
    """The ICT day D queries the vendor's own (ICT) clock: [D 00:00:00, D 23:59:59]."""
    start, end = cloudfone_module._day_window(date(2026, 10, 24))
    assert (start, end) == ("2026-10-24 00:00:00", "2026-10-24 23:59:59")


# The vendor's real 2026-10-26 18:36 rows (verified live, probe of 28/10): the
# 0906004310 call the +7h bug pushed into the 27/10 report and displayed 01:36.
EVENING_4310_LEGS = [
    _leg("2026-10-26T18:36:08", "1793014568.1369-104", "0906004310", "104", "NO ANSWER", 0),
    _leg(
        "2026-10-26T18:36:08",
        "1793014568.1367-3000(Nhóm)",
        "0906004310",
        "3000(Nhóm)",
        "NO ANSWER",
        20,
    ),
    _leg("2026-10-26T18:36:28", "1793014568.1367-hangup", "0906004310", "hangup", "ANSWERED", 0),
]


async def test_regression_4310_evening_call_stays_in_its_own_day_at_its_wall_clock():
    """2026-10-26 18:36 ICT (0906004310, verified live): the vendor returns
    callDate in ICT wall clock, so the call belongs to the 26/10 report and
    shows 18:36 — the old UTC assumption fetched it into the 27/10 report as
    01:36 and dropped the 27/10 evening calls instead."""
    calls = group_call_legs(EVENING_4310_LEGS)
    assert len(calls) == 1
    call = calls[0]
    assert call.call_id == "1793014568"
    assert call.started_at == "2026-10-26T18:36:08"  # wall clock, no shift
    assert call.status == "NO ANSWER"

    # The call time sits inside the 26/10 report window (vendor clock = ICT).
    start, end = cloudfone_module._day_window(date(2026, 10, 26))
    assert start <= "2026-10-26 18:36:08" <= end
    # …and the evening calls of 27/10 (18:05, 19:22 — verified live) sit inside
    # day 27's window; the old D-1 17:00 → D 16:59 window cut them off.
    late_start, late_end = cloudfone_module._day_window(date(2026, 10, 27))
    assert late_start <= "2026-10-27 18:05:53" <= late_end

    # The letter shows 18:36 and buckets the call into the evening slot.
    stats = build_daily_stats(calls)
    html = render_insights_html([], stats, None, date(2026, 10, 26))
    assert "Cuộc gọi nhỡ: 18:36 — 0906004310" in html
    assert "18:00 - 24:00 (Tối)" in html
    assert "1 cuộc (0✓/1✗)" in html


async def test_group_call_legs_status_precedence_no_answer_then_busy():
    """NO ANSWER outranks BUSY when a call carries both leg statuses."""
    calls = group_call_legs(
        [
            _leg(
                "2026-10-01T09:00:00",
                "1791200000.610-2000(Nhóm)",
                "0901234567",
                "2000(Nhóm)",
                "BUSY",
                0,
            ),
            _leg("2026-10-01T09:00:01", "1791200001.612-101", "0901234567", "101", "NO ANSWER", 0),
        ]
    )
    assert len(calls) == 1
    assert calls[0].status == "NO ANSWER"


async def test_group_call_legs_falls_back_to_caller_name():
    """A leg without callerNumber clusters on callerName instead."""
    calls = group_call_legs(
        [
            _leg(
                "2026-10-01T09:00:00",
                "1791200000.610-2000(Nhóm)",
                "",
                "2000(Nhóm)",
                "NO ANSWER",
                0,
                caller_name="Mr A",
            ),
            _leg(
                "2026-10-01T09:00:02",
                "1791200002.612-101",
                "",
                "101",
                "NO ANSWER",
                0,
                caller_name="Mr A",
            ),
        ]
    )
    assert len(calls) == 1
    assert calls[0].caller == "Mr A"


def test_build_daily_stats_on_the_real_2026_10_01_rows():
    """14 live legs → 7 calls: 4 answered, 3 missed, 57.1% answer rate, 88s avg."""
    stats = build_daily_stats(group_call_legs(REAL_DAY_LEGS))
    assert stats.total_calls == 7
    assert stats.answered_calls == 4
    assert stats.missed_calls == 3
    assert stats.answer_rate_pct == 57.1
    assert stats.avg_talk_seconds == 88
    assert stats.missed == (
        ("2026-10-01T07:50:24", "0364489026"),
        ("2026-10-01T07:58:09", "0364489026"),
        ("2026-10-01T16:41:17", "0902065233"),
    )


def test_build_daily_stats_empty_day_is_all_zero():
    stats = build_daily_stats([])
    assert stats == DailyCallStats(
        total_calls=0,
        answered_calls=0,
        missed_calls=0,
        answer_rate_pct=0.0,
        avg_talk_seconds=0,
        missed=(),
    )


async def test_fetch_daily_calls_walks_pages_until_total_is_drained():
    """205 rows = one full page + one remainder page, 1-based PageIndex."""
    seen_pages: list[int] = []
    page_size = cloudfone_module.DEFAULT_PAGE_SIZE

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_pages.append(body["PageIndex"])
        start = (body["PageIndex"] - 1) * page_size
        items = [
            _leg(
                f"2026-10-18T09:{i // 60:02d}:{i % 60:02d}",
                f"1790000000.{i:03d}-101",
                f"09{i:08d}",
                "101",
                "NO ANSWER",
                0,
            )
            for i in range(start, min(start + page_size, 205))
        ]
        return httpx.Response(200, json=_envelope(items, total=205))

    calls = await _transport_client(handler).fetch_daily_calls(day=date(2026, 10, 18))

    assert seen_pages == [1, 2]
    assert len(calls) == 205


async def test_fetch_daily_calls_caps_the_page_walk(caplog):
    """A broken/giant total stops at MAX_DAILY_PAGES with a truncation warning."""
    requests: list[dict] = []
    page_size = cloudfone_module.DEFAULT_PAGE_SIZE

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        base = (body["PageIndex"] - 1) * page_size
        items = [
            _leg(
                "2026-10-18T09:00:00",
                f"1790000000.{base + i:03d}-101",
                f"09{base + i:08d}",
                "101",
                "NO ANSWER",
                0,
            )
            for i in range(page_size)
        ]
        return httpx.Response(200, json=_envelope(items, total=10_000))

    with caplog.at_level("WARNING", logger="app.services.cloudfone"):
        calls = await _transport_client(handler).fetch_daily_calls(day=date(2026, 10, 18))

    assert [r["PageIndex"] for r in requests] == list(
        range(1, cloudfone_module.MAX_DAILY_PAGES + 1)
    )
    assert len(calls) == cloudfone_module.MAX_DAILY_PAGES * page_size
    assert any("truncated" in record.message for record in caplog.records)


async def test_insights_window_is_the_previous_ict_day():
    # 01:00 UTC = 08:00 Vietnam on the 19th → the tick reports on the 18th.
    assert insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)).isoformat() == (
        "2026-10-18"
    )
    assert insights_subject(insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))) == (
        "Cloudfone — Phân tích cuộc gọi ngày 18/10/2026"
    )


async def test_build_insights_fails_soft_per_call(monkeypatch):
    monkeypatch.setattr(cloudfone_module, "LLM_RETRY_DELAY_SECONDS", 0)

    async def flaky_summarizer(_system: str, user: str) -> str:
        if "tốt" in user:
            return "  Khách hỏi về ca làm.  "
        raise RuntimeError("provider down")

    insights = await build_insights(
        [
            CallRecord(call_id="c1", transcript="Khách hỏi tốt về ca làm."),
            CallRecord(call_id="c2", transcript="Khách gọi ngắt giữa chừng."),
            CallRecord(call_id="c3", transcript=""),
        ],
        flaky_summarizer,
    )
    assert insights[0].summary == "Khách hỏi về ca làm."
    assert insights[1].summary is None  # LLM error → empty summary, no raise
    assert insights[2].summary is None  # empty transcript never asks the LLM


async def test_build_insights_retries_a_transient_llm_failure(monkeypatch):
    """One provider blip is retried; the second attempt wins and the summary
    survives. Only a persistent failure leaves the summary empty."""
    monkeypatch.setattr(cloudfone_module, "LLM_RETRY_DELAY_SECONDS", 0)
    attempts: list[str] = []

    async def blip_then_ok(_system: str, user: str) -> str:
        attempts.append(user)
        if len(attempts) == 1:
            raise RuntimeError("transient blip")
        return "  Khách hỏi về giá cước.  "

    insights = await build_insights(
        [CallRecord(call_id="c1", transcript="Khách hỏi giá cước.")], blip_then_ok
    )
    assert insights[0].summary == "Khách hỏi về giá cước."
    assert len(attempts) == 2  # first attempt failed, second succeeded


async def test_build_insights_re_sums_missing_summaries_in_a_second_pass(monkeypatch):
    """A call whose summary is missing after the first sweep gets one more LLM
    sweep; empty-transcript calls never reach the LLM in either sweep."""
    monkeypatch.setattr(cloudfone_module, "LLM_RETRY_DELAY_SECONDS", 0)
    calls_seen: list[str] = []

    async def down_then_up(_system: str, user: str) -> str:
        calls_seen.append(user)
        if len(calls_seen) <= 2:  # both attempts of the first sweep fail
            raise RuntimeError("first sweep down")
        return "Khách hỏi về giá cước."

    insights = await build_insights(
        [
            CallRecord(call_id="c1", transcript="Khách hỏi giá cước."),
            CallRecord(call_id="c2", transcript=""),
        ],
        down_then_up,
    )
    assert insights[0].summary == "Khách hỏi về giá cước."
    assert insights[1].summary is None  # empty transcript: never summarized
    # 2 failed attempts + 1 recovered attempt; the empty call is never asked.
    assert len(calls_seen) == 3
    assert all("BẢN GHI CUỘC GỌI" in user for user in calls_seen)


async def test_build_daily_insights_payload_and_bullets():
    """The LLM gets stats + one compact line per call and returns its bullets."""
    captured: dict = {}

    async def summarizer(system: str, user: str) -> str:
        captured["system"] = system
        captured["user"] = user
        return "– Gọi nhỡ tập trung buổi sáng.\n– Khách 0364489026 gọi lại nhiều lần."

    calls = group_call_legs(REAL_DAY_LEGS)
    stats = build_daily_stats(calls)
    notes = await build_daily_insights(stats, calls, summarizer)

    assert captured["system"] is cloudfone_module.DAILY_INSIGHTS_SYSTEM_PROMPT
    assert "Tổng cuộc gọi: 7 · Trả lời: 4 (57.1%) · Nhỡ: 3" in captured["user"]
    assert "07:50 · 0364489026 · Inbound ·" in captured["user"]  # compact per-call line (ICT)
    assert " · —" in captured["user"]  # calls without a transcript show "—"
    assert notes == "– Gọi nhỡ tập trung buổi sáng.\n– Khách 0364489026 gọi lại nhiều lần."


async def test_build_daily_insights_failures_return_none(monkeypatch):
    monkeypatch.setattr(cloudfone_module, "LLM_RETRY_DELAY_SECONDS", 0)

    assert await build_daily_insights(build_daily_stats([]), [], None) is None

    async def empty_reply(_system: str, _user: str) -> str:
        return "   "

    assert await build_daily_insights(build_daily_stats([]), [], empty_reply) is None

    async def dead(_system: str, _user: str) -> str:
        raise RuntimeError("provider down")

    assert await build_daily_insights(build_daily_stats([]), [], dead) is None


async def test_llm_reasoning_blocks_never_reach_the_letter():
    """Verified live: MiniMax-M2.5 returns reasoning blocks inline in content
    (tags spelled with escapes here so they survive tooling) — the letter must
    ship only the answer, never the reasoning."""
    open_tag = "\x3cthink\x3e"
    close_tag = "\x3c/think\x3e"

    async def reasoning_summarizer(_system: str, _user: str) -> str:
        return (
            f"{open_tag}suy noi bo khong duoc thay\nphan tich them{close_tag}"
            "\u2013 Ghi nhan A.\n\u2013 Ghi nhan B."
        )

    calls = group_call_legs(REAL_DAY_LEGS[4:6])
    notes = await build_daily_insights(build_daily_stats(calls), calls, reasoning_summarizer)
    assert notes == "\u2013 Ghi nhan A.\n\u2013 Ghi nhan B."

    insights = await build_insights(
        [replace(calls[0], transcript="Khach hoi gia.")], reasoning_summarizer
    )
    assert insights[0].summary == "\u2013 Ghi nhan A.\n\u2013 Ghi nhan B."
    html = render_insights_html(insights, build_daily_stats(calls), notes, date(2026, 10, 1))
    assert "suy noi bo" not in html
    assert open_tag not in html


def test_render_insights_html_shows_stats_missed_and_notes():
    calls = group_call_legs(REAL_DAY_LEGS)
    stats = build_daily_stats(calls)
    answered = [call for call in calls if call.status == "ANSWERED"]
    insights = [
        cloudfone_module.CallInsight(transcript=call, summary="Tóm tắt.") for call in answered
    ]
    html = render_insights_html(
        insights,
        stats,
        "– Gọi nhỡ tập trung buổi sáng.\n– Ghi chú khác.",
        date(2026, 10, 1),
    )

    assert "Tổng cuộc gọi: 7 · Trả lời: 4 (57.1%) · Nhỡ: 3 · Thời gian trò chuyện TB: 1p28s" in html
    assert "Cuộc gọi nhỡ: 07:50 — 0364489026; 07:58 — 0364489026; 16:41 — 0902065233" in html
    # Daily notes render above the per-call blocks, one <p> per bullet.
    assert html.index("– Gọi nhỡ tập trung buổi sáng.") < html.index("border-radius:8px")
    assert "<p>– Gọi nhỡ tập trung buổi sáng.</p>" in html
    # Only answered calls get blocks — missed calls live in the missed line.
    assert html.count("border-radius:8px") == 4
    # Call transcripts never ship in the letter — only the LLM summary does.
    assert "<details>" not in html
    assert "Transcript" not in html
    assert "07:50" not in html.split("border-radius:8px")[0].split("Cuộc gọi nhỡ")[0]


def test_render_insights_html_escapes_content():
    row = CallRecord(
        call_id="c1",
        started_at="2026-10-18T09:15:00",
        caller="<script>x</script>",
        direction="inbound",
        talk_seconds=95,
        transcript="Nội dung & chi tiết",
    )
    html = render_insights_html(
        [cloudfone_module.CallInsight(transcript=row, summary="Tóm tắt <b>này</b>")],
        DailyCallStats(
            total_calls=1,
            answered_calls=1,
            missed_calls=0,
            answer_rate_pct=100.0,
            avg_talk_seconds=95,
            missed=(),
        ),
        None,
        date(2026, 10, 18),
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Tóm tắt &lt;b&gt;này&lt;/b&gt;" in html
    assert "1p35s" in html
    assert "Tổng cuộc gọi: 1 · Trả lời: 1 (100.0%) · Nhỡ: 0" in html
    # The transcript text itself must never reach the letter body.
    assert "Nội dung &amp; chi tiết" not in html


def test_render_insights_html_empty_day_keeps_the_placeholder():
    html = render_insights_html(
        [],
        build_daily_stats([]),
        None,
        insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)),
    )
    assert "Không có cuộc gọi nào trong ngày." in html
    assert "Tổng cuộc gọi: 0 · Trả lời: 0 (0.0%) · Nhỡ: 0 · Thời gian trò chuyện TB: 0s" in html


class _FakeSettingsService:
    def __init__(self, cloudfone_cfg, digest_cfg, minimax_cfg=None) -> None:
        self._cloudfone = cloudfone_cfg
        self._digest = digest_cfg
        self._minimax = minimax_cfg or MinimaxRuntimeConfig()

    async def resolve_cloudfone(self):
        return self._cloudfone

    async def resolve_email_digest(self):
        return self._digest

    async def resolve_minimax(self):
        return self._minimax


def _cloudfone_cfg(**overrides):
    values: dict = {
        "service_name": "CloudFone",
        "auth_user": "cloudfone-user",
        "auth_key": "cf-key",
        "recipients": ("ops@vp.vn",),
        "enabled": True,
    }
    values.update(overrides)
    return CloudfoneRuntimeConfig(**values)


async def test_run_disabled_without_recipients_or_toggle():
    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(enabled=False), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_DISABLED

    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(recipients=()), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_DISABLED


async def test_run_unconfigured_without_full_credentials():
    """Auth needs all three credential fields — each gap is reported."""
    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(auth_user=""), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_UNCONFIGURED
    assert result.missing == ["auth_user"]

    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(service_name="", auth_user="", auth_key=""),
            EmailDigestRuntimeConfig(resend_api_key="r"),
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_UNCONFIGURED
    assert result.missing == ["service_name", "auth_user", "auth_key"]


async def test_run_disabled_without_resend_key():
    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="")
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_DISABLED
    assert result.missing == ["resend_api_key"]


async def _fail_fetcher(_day):  # pragma: no cover — must never be reached
    raise AssertionError("fetcher must not run before the config gates pass")


async def test_run_empty_when_the_day_has_no_calls():
    async def fetcher(_day):
        return []

    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=fetcher,
    )
    assert result.status == STATUS_EMPTY


async def _fake_download(url: str) -> bytes:
    return url.encode()


def _fake_transcriber(calls: list[bytes]):
    async def transcriber(audio: bytes) -> str:
        calls.append(audio)
        return f"S1: nội dung {audio.decode()}"

    return transcriber


async def test_run_transcribes_summarizes_and_sends_the_letter(monkeypatch):
    moment = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    seen_audio: list[bytes] = []

    async def fetcher(_day):
        return group_call_legs(REAL_DAY_LEGS)

    async def download(url: str) -> bytes:
        return url.encode()

    async def summarizer(system: str, user: str) -> str:
        if system is cloudfone_module.DAILY_INSIGHTS_SYSTEM_PROMPT:
            return "– Khách 0364489026 gọi lại 3 lần."
        return "Khách hỏi về giá dịch vụ."

    sent: dict = {}

    async def sender(**kwargs):
        sent.update(kwargs)
        return "resend-id-1"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    result = await run_cloudfone_insights(
        None,
        now=moment,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="resend-key")
        ),
        summarizer=summarizer,
        fetcher=fetcher,
        transcriber=_fake_transcriber(seen_audio),
        sender=sender,
    )

    assert result.status == STATUS_SENT
    assert result.provider_id == "resend-id-1"
    assert result.transcript_count == 4  # answered calls fetched
    assert result.insights_count == 4  # one insight per answered call
    assert result.transcribed_count == 4  # answered calls with recording + talk time
    # Only recorded calls with real talk time reach the transcriber — the
    # ring-only 07:50 / 07:58 / 16:41 recordings are noise and stay skipped.
    assert len(seen_audio) == 4
    assert sent["api_key"] == "resend-key"
    assert sent["to"] == ["ops@vp.vn"]
    assert sent["subject"] == "Cloudfone — Phân tích cuộc gọi ngày 01/10/2026"
    html = sent["html"]
    assert "Tổng cuộc gọi: 7 · Trả lời: 4 (57.1%) · Nhỡ: 3 · Thời gian trò chuyện TB: 1p28s" in html
    assert "Cuộc gọi nhỡ: 07:50 — 0364489026; 07:58 — 0364489026; 16:41 — 0902065233" in html
    assert "Khách hỏi về giá dịch vụ." in html  # per-call summaries render
    assert "S1: nội dung" not in html  # transcripts never ship in the letter
    assert "– Khách 0364489026 gọi lại 3 lần." in html
    assert len(sent.get("attachments", [])) == 1
    att = sent["attachments"][0]
    assert att.filename == "Bao-cao-tong-dai-20261001.docx"
    assert (
        att.content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(att.content) > 20000


async def test_run_transcriber_failure_isolates_the_call(monkeypatch):
    async def fetcher(_day):
        return group_call_legs(REAL_DAY_LEGS)

    async def download(url: str) -> bytes:
        if "rec-1702" in url:
            raise CloudfoneError("CloudFone trả lỗi HTTP 404 cho bản ghi")
        return url.encode()

    seen_audio: list[bytes] = []

    async def sender(**kwargs):
        return "resend-id-1"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    result = await run_cloudfone_insights(
        None,
        now=datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc),
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        summarizer=None,
        fetcher=fetcher,
        transcriber=_fake_transcriber(seen_audio),
        sender=sender,
    )

    assert result.status == STATUS_SENT
    assert result.transcribed_count == 3  # the 17:02 call keeps an empty transcript
    assert len(seen_audio) == 3


async def test_run_skips_transcription_without_minimax_key(monkeypatch):
    """No stored MiniMax key → no downloads at all, letter still sends."""

    async def fetcher(_day):
        return group_call_legs(REAL_DAY_LEGS)

    async def no_download(_url: str) -> bytes:  # pragma: no cover — must not run
        raise AssertionError("download must be skipped without an STT key")

    async def sender(**kwargs):
        return "resend-id-1"

    monkeypatch.setattr(cloudfone_module, "download_recording", no_download)
    result = await run_cloudfone_insights(
        None,
        now=datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc),
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        summarizer=None,
        fetcher=fetcher,
        sender=sender,
    )

    assert result.status == STATUS_SENT
    assert result.transcribed_count == 0


async def test_run_default_transcriber_uses_the_stored_minimax_key(monkeypatch):
    """Without an injected transcriber the tick builds one from minimax_api_key."""
    captured: dict = {}

    class _FakeAsrClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

        async def transcribe(self, audio: bytes) -> str:
            return f"transcript:{audio.decode()}"

    async def fetcher(_day):
        return group_call_legs(REAL_DAY_LEGS)

    async def download(url: str) -> bytes:
        return url.encode()

    async def sender(**kwargs):
        return "resend-id-1"

    monkeypatch.setattr(cloudfone_module, "MiniMaxAsrClient", _FakeAsrClient)
    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    result = await run_cloudfone_insights(
        None,
        now=datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc),
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(),
            EmailDigestRuntimeConfig(resend_api_key="r"),
            MinimaxRuntimeConfig(api_key="mk-key"),
        ),
        summarizer=None,
        fetcher=fetcher,
        sender=sender,
    )

    assert captured["api_key"] == "mk-key"
    assert result.status == STATUS_SENT
    assert result.transcribed_count == 4


async def test_run_respects_the_daily_transcription_bound(monkeypatch, caplog):
    async def fetcher(_day):
        return [
            CallRecord(
                call_id=f"c{i}",
                started_at=f"2026-10-01T09:{i:02d}:00",
                caller=f"09{i:08d}",
                status="ANSWERED",
                talk_seconds=30,
                recording_url=f"https://rec/{i}",
            )
            for i in range(4)
        ]

    async def download(url: str) -> bytes:
        return url.encode()

    seen_audio: list[bytes] = []

    async def sender(**kwargs):
        return "resend-id-1"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    monkeypatch.setattr(cloudfone_module, "MAX_TRANSCRIPTIONS_PER_DAY", 2)
    with caplog.at_level("WARNING", logger="app.services.cloudfone"):
        result = await run_cloudfone_insights(
            None,
            now=datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc),
            settings_service=_FakeSettingsService(
                _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
            ),
            summarizer=None,
            fetcher=fetcher,
            transcriber=_fake_transcriber(seen_audio),
            sender=sender,
        )

    assert result.status == STATUS_SENT
    assert result.transcribed_count == 2
    assert len(seen_audio) == 2
    assert any("bound reached" in record.message for record in caplog.records)


async def test_run_daily_notes_are_omitted_when_the_llm_call_fails(monkeypatch):
    monkeypatch.setattr(cloudfone_module, "LLM_RETRY_DELAY_SECONDS", 0)
    from dataclasses import replace

    async def fetcher(_day):
        return [
            replace(group_call_legs(REAL_DAY_LEGS[4:6])[0], transcript="Khách hỏi giá dịch vụ.")
        ]

    async def summarizer(system: str, _user: str) -> str:
        if system is cloudfone_module.DAILY_INSIGHTS_SYSTEM_PROMPT:
            raise RuntimeError("provider down")
        return "Khách hỏi về giá dịch vụ."

    sent: dict = {}

    async def sender(**kwargs):
        sent.update(kwargs)
        return "resend-id-1"

    result = await run_cloudfone_insights(
        None,
        now=datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc),
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        summarizer=summarizer,
        fetcher=fetcher,
        sender=sender,
    )

    assert result.status == STATUS_SENT
    assert "– " not in sent["html"]
    assert "Khách hỏi về giá dịch vụ." in sent["html"]


async def test_run_reports_a_rejected_email_without_raising():
    async def fetcher(_day):
        return [CallRecord(call_id="c1", status="ANSWERED", talk_seconds=5, transcript="hi")]

    async def sender(**_kwargs):
        raise EmailDeliveryError("Resend rejected the email (status 422)")

    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="resend-key")
        ),
        fetcher=fetcher,
        sender=sender,
    )
    assert result.status == STATUS_UNCONFIGURED
    assert "422" in (result.error or "")


async def test_run_surfaces_a_cloudfone_fetch_failure():
    async def fetcher(_day):
        raise CloudfoneError("CloudFone không phản hồi: boom")

    result = await run_cloudfone_insights(
        None,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=fetcher,
    )
    assert result.status == STATUS_UNCONFIGURED
    assert "boom" in (result.error or "")


async def test_download_recording_accepts_wav_and_rejects_the_rest(monkeypatch):
    from app.core.http import register_test_client

    wav = b"RIFF\x08\x00\x00\x00WAVEdata"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=wav)

    register_test_client(
        "cloudfone_recording",
        httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://90.cloudfone.vn"
        ),
    )
    assert await cloudfone_module.download_recording("https://90.cloudfone.vn/Home?ID=x") == wav

    def handler_html(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not a wav</html>")

    register_test_client(
        "cloudfone_recording",
        httpx.AsyncClient(
            transport=httpx.MockTransport(handler_html), base_url="https://90.cloudfone.vn"
        ),
    )
    with pytest.raises(CloudfoneError, match="không phải WAV"):
        await cloudfone_module.download_recording("https://90.cloudfone.vn/Home?ID=x")

    monkeypatch.setattr(cloudfone_module, "MAX_RECORDING_BYTES", 8)
    with pytest.raises(CloudfoneError, match="50MB"):
        await cloudfone_module.download_recording("https://90.cloudfone.vn/Home?ID=x")

    def handler_404(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    register_test_client(
        "cloudfone_recording",
        httpx.AsyncClient(
            transport=httpx.MockTransport(handler_404), base_url="https://90.cloudfone.vn"
        ),
    )
    with pytest.raises(CloudfoneError, match="404"):
        await cloudfone_module.download_recording("https://90.cloudfone.vn/Home?ID=x")


def test_generate_daily_call_report_docx_creates_valid_document_with_charts():
    import io
    import zipfile
    import docx
    from app.services.cloudfone_report import generate_daily_call_report_docx

    calls = group_call_legs(REAL_DAY_LEGS)
    stats = build_daily_stats(calls)
    answered = [c for c in calls if c.status == "ANSWERED"]
    insights = [cloudfone_module.CallInsight(c, summary="Tóm tắt cuộc gọi") for c in answered]
    notes = "– Inbound gọi nhỡ nhiều\n– Cần Callback gấp\n– Hệ thống ghi nhận"
    day = date(2026, 10, 1)

    docx_bytes = generate_daily_call_report_docx(stats, calls, insights, notes, day)
    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 20000

    doc = docx.Document(io.BytesIO(docx_bytes))
    assert len(doc.tables) >= 3
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        media = [name for name in z.namelist() if "media/" in name]
        assert len(media) == 2

    # Verify no mention of "AI", English jargon, or bureaucratic sign-off blocks
    all_text = (
        " ".join(p.text for p in doc.paragraphs)
        + " "
        + " ".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    )
    assert "AI" not in all_text
    assert "Ban Vận Hành" not in all_text
    assert "NGƯỜI LẬP BÁO CÁO" not in all_text
    assert "BAN GIÁM ĐỐC" not in all_text
    assert "CÔNG TY TNHH VẬN TẢI & LOGISTICS TING TING" not in all_text
    assert "NO ANSWER" not in all_text
    assert "(AHT)" not in all_text
    assert "CALLBACK ACTION" not in all_text
    assert "Inbound" not in all_text
    assert "Callback" not in all_text


def test_report_docx_never_embeds_call_transcripts():
    """The report file carries per-call summaries only — even when the LLM
    summary is missing, the raw transcript text must not leak into the DOCX."""
    import io

    import docx

    from app.services.cloudfone_report import generate_daily_call_report_docx

    calls = group_call_legs(REAL_DAY_LEGS)
    stats = build_daily_stats(calls)
    answered = [c for c in calls if c.status == "ANSWERED"]
    leak = "S1: alo chị ơi khách hỏi giá cước nội dung riêng tư."
    transcript_calls = [replace(c, transcript=leak) for c in answered]
    insights = [cloudfone_module.CallInsight(c, summary=None) for c in transcript_calls]

    docx_bytes = generate_daily_call_report_docx(
        stats, transcript_calls, insights, None, date(2026, 10, 1)
    )
    doc = docx.Document(io.BytesIO(docx_bytes))
    all_text = (
        " ".join(p.text for p in doc.paragraphs)
        + " "
        + " ".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    )
    assert leak not in all_text
    assert "nội dung riêng tư" not in all_text
    assert "(Chưa có tóm tắt)" in all_text


# --- transcript cache: TranscriptStore seam over cloudfone_call_transcripts ---


class _FakeTranscriptStore:
    def __init__(self, preload: dict[str, str] | None = None) -> None:
        self.rows: dict[str, str] = dict(preload or {})
        self.saved: list[tuple[str, str, date]] = []
        self.load_calls: list[str] = []
        self.fail_load = False
        self.fail_save = False

    async def load(self, call_id: str) -> str | None:
        self.load_calls.append(call_id)
        if self.fail_load:
            raise RuntimeError("cache read down")
        return self.rows.get(call_id)

    async def save(self, call: CallRecord, transcript: str, day: date) -> None:
        if self.fail_save:
            raise RuntimeError("cache write down")
        self.rows[call.call_id] = transcript
        self.saved.append((call.call_id, transcript, day))


def _stt_eligible() -> list[CallRecord]:
    return [c for c in group_call_legs(REAL_DAY_LEGS) if c.recording_url and c.talk_seconds > 0]


def _cached_day() -> dict[str, str]:
    return {c.call_id: f"bản ghi đã lưu {c.call_id}" for c in _stt_eligible()}


async def _real_day_fetcher(_day):
    return group_call_legs(REAL_DAY_LEGS)


def _flat_summarizer():
    async def summarizer(_system: str, _user: str) -> str:
        return "Tóm tắt."

    return summarizer


def _capturing_sender(sent: dict):
    async def sender(**kwargs):
        sent.update(kwargs)
        return "resend-id-1"

    return sender


async def test_stored_transcripts_skip_download_and_stt(monkeypatch):
    moment = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    store = _FakeTranscriptStore(_cached_day())
    stt_calls: list[bytes] = []
    sent: dict = {}

    async def no_download(url: str) -> bytes:
        raise AssertionError("cache hit must not download the recording")

    async def transcriber(audio: bytes) -> str:
        stt_calls.append(audio)
        return "S1: không được gọi"

    monkeypatch.setattr(cloudfone_module, "download_recording", no_download)
    result = await run_cloudfone_insights(
        None,
        now=moment,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_real_day_fetcher,
        transcriber=transcriber,
        sender=_capturing_sender(sent),
        transcript_store=store,
    )

    assert result.status == STATUS_SENT
    assert result.transcribed_count == 4
    assert stt_calls == []
    assert store.saved == []  # cache hits are never re-persisted
    # Cache hits feed the pipeline (transcribed_count above); the transcript
    # text itself never renders in the letter.
    assert "bản ghi đã lưu" not in sent["html"]


async def test_fresh_transcripts_are_stored_for_the_next_run(monkeypatch):
    moment = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    store = _FakeTranscriptStore()
    sent: dict = {}

    async def download(url: str) -> bytes:
        return url.encode()

    async def transcriber(audio: bytes) -> str:
        return f"S1: nội dung {audio.decode()}"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    result = await run_cloudfone_insights(
        None,
        now=moment,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_real_day_fetcher,
        transcriber=transcriber,
        sender=_capturing_sender(sent),
        transcript_store=store,
    )

    assert result.status == STATUS_SENT
    assert result.transcribed_count == 4
    assert len(store.saved) == 4
    assert {cid for cid, _text, _day in store.saved} == {c.call_id for c in _stt_eligible()}
    # The stored day is the insights window day — analysis can query by date.
    assert {day for _cid, _text, day in store.saved} == {date(2026, 10, 1)}
    assert all(text.startswith("S1: nội dung ") for _cid, text, _day in store.saved)


async def test_store_failures_stay_fail_soft(monkeypatch, caplog):
    moment = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    store = _FakeTranscriptStore()
    store.fail_load = True
    store.fail_save = True
    sent: dict = {}

    async def download(url: str) -> bytes:
        return url.encode()

    async def transcriber(audio: bytes) -> str:
        return f"S1: nội dung {audio.decode()}"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    with caplog.at_level("WARNING", logger="app.services.cloudfone"):
        result = await run_cloudfone_insights(
            None,
            now=moment,
            settings_service=_FakeSettingsService(
                _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
            ),
            fetcher=_real_day_fetcher,
            transcriber=transcriber,
            sender=_capturing_sender(sent),
            transcript_store=store,
        )

    # A cache outage costs only the cache: STT fills the letter and the send goes out.
    assert result.status == STATUS_SENT
    assert result.transcribed_count == 4
    assert store.saved == []
    assert any("cache read failed" in record.message for record in caplog.records)
    assert any("cache write failed" in record.message for record in caplog.records)


async def test_rerun_reuses_stored_transcripts_and_never_retranscribes(monkeypatch):
    moment = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    store = _FakeTranscriptStore()
    stt_calls: list[bytes] = []
    downloads: list[str] = []

    async def download(url: str) -> bytes:
        downloads.append(url)
        return url.encode()

    async def transcriber(audio: bytes) -> str:
        stt_calls.append(audio)
        return f"S1: nội dung {audio.decode()}"

    monkeypatch.setattr(cloudfone_module, "download_recording", download)
    kwargs = dict(
        now=moment,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_real_day_fetcher,
        transcriber=transcriber,
        sender=_capturing_sender({}),
        transcript_store=store,
    )
    first = await run_cloudfone_insights(None, **kwargs)
    assert first.transcribed_count == 4
    assert len(downloads) == 4
    assert len(stt_calls) == 4

    second = await run_cloudfone_insights(None, **kwargs)

    # The rerun pays nothing: no recording download, no STT, no duplicate rows.
    assert second.status == STATUS_SENT
    assert second.transcribed_count == 4
    assert len(downloads) == 4
    assert len(stt_calls) == 4
    assert len(store.saved) == 4


async def test_stored_transcripts_fill_the_letter_without_an_stt_provider(monkeypatch):
    """Empty MiniMax key (transcriber None): cache hits still produce a letter."""
    moment = datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc)
    store = _FakeTranscriptStore(_cached_day())
    sent: dict = {}

    async def no_download(url: str) -> bytes:
        raise AssertionError("no STT provider means no download either")

    monkeypatch.setattr(cloudfone_module, "download_recording", no_download)
    result = await run_cloudfone_insights(
        None,
        now=moment,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_real_day_fetcher,
        sender=_capturing_sender(sent),
        transcript_store=store,
    )

    assert result.status == STATUS_SENT
    assert result.transcribed_count == 4
    assert "bản ghi đã lưu" not in sent["html"]  # transcripts never ship in the letter
