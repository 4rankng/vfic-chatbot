"""ODS service: CloudFone client, daily fetch, insights build, and the pass.

The client's transport is injected (``httpx.MockTransport``), the summarizer
and the sender are callables — no network and no graph import anywhere here.
"""

# pyright: reportArgumentType=false

import json
from datetime import datetime, timezone

import httpx
import pytest

import app.services.ods as ods_module
from app.services.email_service import EmailDeliveryError
from app.services.integration_settings import EmailDigestRuntimeConfig, OdsRuntimeConfig
from app.services.ods import (
    STATUS_DISABLED,
    STATUS_EMPTY,
    STATUS_SENT,
    STATUS_UNCONFIGURED,
    CallTranscript,
    CloudfoneError,
    OdsCloudfoneClient,
    build_insights,
    insights_subject,
    insights_window,
    render_insights_html,
    run_ods_insights,
)


def _envelope(items: list[dict]) -> dict:
    return {"result": "success", "data": {"data": items}}


def _transport_client(handler) -> OdsCloudfoneClient:
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

    return OdsCloudfoneClient("cf-key", transport=transport)


async def test_client_posts_service_and_key_in_the_body():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_envelope([]))

    client = _transport_client(handler)
    rows = await client.get_call_logs(limit=1)

    assert rows == []
    assert seen["url"].endswith("/GetCallLogs")
    assert seen["body"]["Service"] == "CloudFone"
    assert seen["body"]["APIKey"] == "cf-key"
    assert seen["body"]["Limit"] == 1
    # The key must never ride the query string (proxy logs stay clean).
    assert "cf-key" not in seen["url"]


async def test_fetch_daily_transcripts_uses_yesterdays_full_day_range():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_envelope(
                [
                    {
                        "CallID": "c1",
                        "Phone": "0901234567",
                        "Direction": "inbound",
                        "Agent": "ext-11",
                        "Duration": "125",
                        "StartTime": "2026-10-18 09:15:00",
                        "Transcript": "Chào anh, em gọi hỏi về ca làm việc.",
                    },
                    {"id": "c2", "transcript": "Không rõ lỗi gì ạ."},
                ]
            ),
        )

    client = _transport_client(handler)
    day = insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))
    transcripts = await client.fetch_daily_transcripts(day=day)

    assert seen["url"].endswith("/GetHistoryCallAnalytics")
    assert seen["body"]["FromDate"] == day.isoformat()
    assert seen["body"]["ToDate"] == day.isoformat()
    assert [t.call_id for t in transcripts] == ["c1", "c2"]
    assert transcripts[0].phone == "0901234567"
    assert transcripts[0].duration_seconds == 125
    assert transcripts[0].transcript.startswith("Chào anh")
    assert transcripts[1].transcript == "Không rõ lỗi gì ạ."


async def test_client_rejects_a_non_success_result():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "error", "message": "Invalid APIKey"})

    with pytest.raises(CloudfoneError, match="Invalid APIKey"):
        await _transport_client(handler).get_call_logs(limit=1)


async def test_insights_window_is_the_previous_ict_day():
    # 01:00 UTC = 08:00 Vietnam on the 19th → the tick reports on the 18th.
    assert insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)).isoformat() == (
        "2026-10-18"
    )
    assert insights_subject(insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc))) == (
        "ODS — Phân tích cuộc gọi ngày 18/10/2026"
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
        [ods_module.CallInsight(transcript=row, summary="Tóm tắt <b>này</b>")],
        insights_window(datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)),
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Tóm tắt &lt;b&gt;này&lt;/b&gt;" in html
    assert "1p35s" in html
    assert "Tổng số cuộc gọi: <b>1</b>" in html


class _FakeSettingsService:
    def __init__(self, ods_cfg, digest_cfg) -> None:
        self._ods = ods_cfg
        self._digest = digest_cfg

    async def resolve_ods(self):
        return self._ods

    async def resolve_email_digest(self):
        return self._digest


def _ods_cfg(**overrides):
    values: dict = {
        "api_key": "cf-key",
        "recipients": ("ops@vp.vn",),
        "enabled": True,
    }
    values.update(overrides)
    return OdsRuntimeConfig(**values)


async def test_run_disabled_without_recipients_or_toggle():
    result = await run_ods_insights(
        None,
        settings_service=_FakeSettingsService(
            _ods_cfg(enabled=False), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_DISABLED

    result = await run_ods_insights(
        None,
        settings_service=_FakeSettingsService(
            _ods_cfg(recipients=()), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_DISABLED


async def test_run_unconfigured_without_api_key():
    result = await run_ods_insights(
        None,
        settings_service=_FakeSettingsService(
            _ods_cfg(api_key=""), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=_fail_fetcher,
    )
    assert result.status == STATUS_UNCONFIGURED
    assert result.missing == ["api_key"]


async def test_run_disabled_without_resend_key():
    result = await run_ods_insights(
        None,
        settings_service=_FakeSettingsService(
            _ods_cfg(), EmailDigestRuntimeConfig(resend_api_key="")
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

    result = await run_ods_insights(
        None,
        settings_service=_FakeSettingsService(
            _ods_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
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

    result = await run_ods_insights(
        None,
        now=moment,
        settings_service=_FakeSettingsService(
            _ods_cfg(), EmailDigestRuntimeConfig(resend_api_key="resend-key")
        ),
        summarizer=summarizer,
        fetcher=fetcher,
        sender=sender,
    )
    assert result.status == STATUS_SENT
    assert result.provider_id == "resend-id-1"
    assert sent["api_key"] == "resend-key"
    assert sent["to"] == ["ops@vp.vn"]
    assert sent["subject"] == "ODS — Phân tích cuộc gọi ngày 18/10/2026"
    assert "Khách hỏi về giá dịch vụ." in sent["html"]


async def test_run_reports_a_rejected_email_without_raising():
    async def fetcher(_day):
        return [CallTranscript(call_id="c1", transcript="hi")]

    async def sender(**_kwargs):
        raise EmailDeliveryError("Resend rejected the email (status 422)")

    result = await run_ods_insights(
        None,
        settings_service=_FakeSettingsService(
            _ods_cfg(), EmailDigestRuntimeConfig(resend_api_key="resend-key")
        ),
        fetcher=fetcher,
        sender=sender,
    )
    assert result.status == STATUS_UNCONFIGURED
    assert "422" in (result.error or "")


async def test_run_surfaces_a_cloudfone_fetch_failure():
    async def fetcher(_day):
        raise CloudfoneError("CloudFone không phản hồi: boom")

    result = await run_ods_insights(
        None,
        settings_service=_FakeSettingsService(
            _ods_cfg(), EmailDigestRuntimeConfig(resend_api_key="r")
        ),
        fetcher=fetcher,
    )
    assert result.status == STATUS_UNCONFIGURED
    assert "boom" in (result.error or "")
