"""Cloudfone service: CloudFone client (GetCallLogs spec 1.1), daily fetch,
insights build, and the pass.

The client's transport is injected (``httpx.MockTransport``), the summarizer
and the sender are callables — no network and no graph import anywhere here.
"""

# pyright: reportArgumentType=false

import json
from datetime import datetime, timezone

import httpx
import pytest

import app.services.cloudfone as cloudfone_module
from app.services.email_service import EmailDeliveryError
from app.services.integration_settings import EmailDigestRuntimeConfig, CloudfoneRuntimeConfig
from app.services.cloudfone import (
    STATUS_DISABLED,
    STATUS_EMPTY,
    STATUS_SENT,
    STATUS_UNCONFIGURED,
    CallTranscript,
    CloudfoneError,
    CloudfoneClient,
    build_insights,
    insights_subject,
    insights_window,
    render_insights_html,
    run_cloudfone_insights,
)


def _envelope(items: list[dict], *, total: int | None = None) -> dict:
    """The spec-1.1 success envelope: result/message/total/data(list)."""
    return {
        "result": "success",
        "message": "",
        "total": len(items) if total is None else total,
        "data": items,
    }


def _row(index: int) -> dict:
    return {
        "CallID": f"c{index}",
        "Phone": "0901234567",
        "Direction": "inbound",
        "Agent": "ext-11",
        "Duration": "125",
        "StartTime": "2026-10-18 09:15:00",
        "Transcript": f"Giao tiếp số {index}.",
    }


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


class _FrozenDateTime(datetime):
    """Module-level datetime stand-in: 01:00 UTC = 08:00 ICT on the 19th."""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 — the frozen instant ignores the tz
        return datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)


async def test_get_call_logs_sends_the_spec_1_1_body(monkeypatch):
    """Auth trio + all required spec fields, correct names, nothing legacy."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope([]))

    monkeypatch.setattr(cloudfone_module, "datetime", _FrozenDateTime)
    rows = await _transport_client(handler).get_call_logs(page_index=0, page_size=5)

    assert rows == []
    assert seen["url"].endswith("/GetCallLogs")
    # Spec auth: three separate credential fields in the JSON body.
    assert seen["body"]["ServiceName"] == "CloudFone"
    assert seen["body"]["AuthUser"] == "cloudfone-user"
    assert seen["body"]["AuthKey"] == "cf-key"
    # Required request fields per the spec's REQUEST table.
    assert seen["body"]["Direction"] == "all"  # default covers both ways
    assert seen["body"]["DateStart"] == "2026-10-18 00:00:01"  # yesterday
    assert seen["body"]["DateEnd"] == "2026-10-19 23:59:59"  # → today
    assert seen["body"]["PageIndex"] == 0
    assert seen["body"]["PageSize"] == 5
    # The pre-spec field names are gone for good.
    for legacy in ("Service", "APIKey", "Limit"):
        assert legacy not in seen["body"]
    # The key must never ride the query string (proxy logs stay clean).
    assert "cf-key" not in seen["url"]


async def test_get_call_logs_honors_an_explicit_window_and_direction():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope([]))

    await _transport_client(handler).get_call_logs(
        date_start="2026-10-01 00:00:01",
        date_end="2026-10-02 23:59:59",
        direction="inbound",
    )
    assert seen["body"]["DateStart"] == "2026-10-01 00:00:01"
    assert seen["body"]["DateEnd"] == "2026-10-02 23:59:59"
    assert seen["body"]["Direction"] == "inbound"


async def test_client_rejects_a_non_success_result():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "error", "message": "Invalid APIKey"})

    with pytest.raises(CloudfoneError, match="Invalid APIKey"):
        await _transport_client(handler).get_call_logs(page_index=0, page_size=5)


async def test_client_rejects_the_live_failure_envelope():
    """The verified live shape: HTTP 200, result=failure, empty message."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"result": "failure", "message": "", "total": 0, "data": None}
        )

    with pytest.raises(CloudfoneError, match="không rõ lý do"):
        await _transport_client(handler).get_call_logs(page_index=0, page_size=5)


async def test_fetch_daily_transcripts_uses_the_spec_day_window():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_envelope(
                [
                    _row(1),
                    {"id": "c2", "transcript": "Không rõ lỗi gì ạ."},
                ]
            ),
        )

    client = _transport_client(handler)
    day = insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))
    transcripts = await client.fetch_daily_transcripts(day=day)

    assert seen["url"].endswith("/GetCallLogs")
    assert seen["body"]["DateStart"] == f"{day.isoformat()} 00:00:01"
    assert seen["body"]["DateEnd"] == f"{day.isoformat()} 23:59:59"
    assert seen["body"]["Direction"] == "all"
    assert seen["body"]["PageIndex"] == 0
    assert seen["body"]["PageSize"] == cloudfone_module.DEFAULT_PAGE_SIZE
    assert seen["body"]["IsSort"] == 1
    assert [t.call_id for t in transcripts] == ["c1", "c2"]
    assert transcripts[0].phone == "0901234567"
    assert transcripts[0].duration_seconds == 125
    assert transcripts[0].transcript.startswith("Giao tiếp số 1")
    assert transcripts[1].transcript == "Không rõ lỗi gì ạ."


async def test_fetch_daily_transcripts_walks_pages_until_total_is_drained():
    """205 rows = one full page + one remainder page, then the loop stops."""
    seen_pages: list[int] = []
    page_size = cloudfone_module.DEFAULT_PAGE_SIZE

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_pages.append(body["PageIndex"])
        start = body["PageIndex"] * page_size
        items = [_row(i) for i in range(start, min(start + page_size, 205))]
        return httpx.Response(200, json=_envelope(items, total=205))

    transcripts = await _transport_client(handler).fetch_daily_transcripts(
        day=cloudfone_module.insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))
    )

    assert seen_pages == [0, 1]
    assert len(transcripts) == 205


async def test_fetch_daily_transcripts_caps_the_page_walk(caplog):
    """A broken/giant total stops at MAX_DAILY_PAGES with a truncation warning."""
    requests: list[dict] = []
    page_size = cloudfone_module.DEFAULT_PAGE_SIZE

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        items = [_row(i) for i in range(page_size)]  # always a full page
        return httpx.Response(200, json=_envelope(items, total=10_000))

    with caplog.at_level("WARNING", logger="app.services.cloudfone"):
        transcripts = await _transport_client(handler).fetch_daily_transcripts(
            day=cloudfone_module.insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))
        )

    assert [r["PageIndex"] for r in requests] == list(range(cloudfone_module.MAX_DAILY_PAGES))
    assert len(transcripts) == cloudfone_module.MAX_DAILY_PAGES * page_size
    assert any("truncated" in record.message for record in caplog.records)


async def test_insights_window_is_the_previous_ict_day():
    # 01:00 UTC = 08:00 Vietnam on the 19th → the tick reports on the 18th.
    assert insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)).isoformat() == (
        "2026-10-18"
    )
    assert insights_subject(insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))) == (
        "Cloudfone — Phân tích cuộc gọi ngày 18/10/2026"
    )


async def test_build_insights_fails_soft_per_transcript():
    async def flaky_summarizer(_system: str, user: str) -> str:
        if "tốt" in user:
            return "  Khách hỏi về ca làm.  "
        raise RuntimeError("provider down")

    insights = await build_insights(
        [
            CallTranscript(call_id="c1", transcript="Khách hỏi tốt về ca làm."),
            CallTranscript(call_id="c2", transcript="Khách gọi ngắt giữa chừng."),
            CallTranscript(call_id="c3", transcript=""),
        ],
        flaky_summarizer,
    )
    assert insights[0].summary == "Khách hỏi về ca làm."
    assert insights[1].summary is None  # LLM error → empty summary, no raise
    assert insights[2].summary is None  # empty transcript never asks the LLM


def test_render_insights_html_escapes_content():
    row = CallTranscript(
        call_id="c1",
        phone="<script>x</script>",
        direction="inbound",
        duration_seconds=95,
        transcript="Nội dung & chi tiết",
    )
    html = render_insights_html(
        [cloudfone_module.CallInsight(transcript=row, summary="Tóm tắt <b>này</b>")],
        insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)),
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Tóm tắt &lt;b&gt;này&lt;/b&gt;" in html
    assert "1p35s" in html
    assert "Tổng số cuộc gọi: <b>1</b>" in html


class _FakeSettingsService:
    def __init__(self, cloudfone_cfg, digest_cfg) -> None:
        self._cloudfone = cloudfone_cfg
        self._digest = digest_cfg

    async def resolve_cloudfone(self):
        return self._cloudfone

    async def resolve_email_digest(self):
        return self._digest


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
    """Spec 1.1 needs all three credential fields — each gap is reported."""
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


async def test_run_sends_the_insights_email_to_recipients():
    moment = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)

    async def fetcher(_day):
        return [CallTranscript(call_id="c1", phone="09", transcript="Khách hỏi giá.")]

    async def summarizer(_system: str, _user: str) -> str:
        return "Khách hỏi về giá dịch vụ."

    sent: dict = {}

    async def sender(**kwargs):
        sent.update(kwargs)
        return "resend-id-1"

    result = await run_cloudfone_insights(
        None,
        now=moment,
        settings_service=_FakeSettingsService(
            _cloudfone_cfg(), EmailDigestRuntimeConfig(resend_api_key="resend-key")
        ),
        summarizer=summarizer,
        fetcher=fetcher,
        sender=sender,
    )
    assert result.status == STATUS_SENT
    assert result.provider_id == "resend-id-1"
    assert sent["api_key"] == "resend-key"
    assert sent["to"] == ["ops@vp.vn"]
    assert sent["subject"] == "Cloudfone — Phân tích cuộc gọi ngày 18/10/2026"
    assert "Khách hỏi về giá dịch vụ." in sent["html"]


async def test_run_reports_a_rejected_email_without_raising():
    async def fetcher(_day):
        return [CallTranscript(call_id="c1", transcript="hi")]

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
