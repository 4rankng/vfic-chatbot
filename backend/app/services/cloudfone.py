"""Cloudfone daily voice-transcript insights: fetch → summarize → email.

Cloudfone is the vendor label for the CloudFone-hosted call center (the underlying
HTTP API stays ``api.cloudfone.vn``). One ``run_cloudfone_insights`` pass: resolve
the admin config, fetch the previous full day's call analytics (voice
transcripts) from CloudFone, summarize each transcript through the shared
digest summarizer (injected — services must not import the graph layer), and
email the insights to the admin-configured recipients through the same Resend
sender the candidate digest uses. Re-running a day is idempotent: the tick
always reports on the previous full day and no send-state row exists.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import CLOUDFONE_API_BASE
from app.services.email_digest.renderer import DIGEST_FROM_EMAIL
from app.services.email_service import EmailDeliveryError, send_email_via_resend
from app.services.integration_settings.service import IntegrationSettingsService

logger = logging.getLogger(__name__)

ICT = ZoneInfo("Asia/Ho_Chi_Minh")  # Vietnam — GMT+7, no DST

# Bounded human-readable statuses for the tick log line.
STATUS_DISABLED = "disabled"  # toggle off, no recipients, or no Resend key
STATUS_UNCONFIGURED = "unconfigured"  # enabled with recipients but no Cloudfone key
STATUS_EMPTY = "empty"  # fetched fine, but the previous day had no transcripts
STATUS_SENT = "sent"

CloudfoneTransport = Callable[[str, dict], Awaitable[dict]]

# GetCallLogs spec 1.1 defaults: page geometry for the daily fetch and the
# admin probe, plus the all-directions filter (both inbound and outbound).
DEFAULT_DIRECTION = "all"
DEFAULT_PAGE_SIZE = 200
# Bounds one day's fetch at 5 × 200 rows — any real day fits; see
# fetch_daily_transcripts for the truncation behavior past the bound.
MAX_DAILY_PAGES = 5

INSIGHTS_SYSTEM_PROMPT = (
    "Bạn là trợ lý phân tích cuộc gọi tổng đài. Viết 2-4 câu tiếng Việt tóm tắt "
    "nội dung cuộc giao tiếp trong bản ghi (transcript) cuộc gọi: người gọi hỏi/về "
    "việc gì, nhân viên tổng đài trả lời thế nào, và kết quả cuộc gọi.\n"
    "QUY TẮC BẮT BUỘC:\n"
    "- KHÔNG suy đoán thông tin không có trong transcript; thiếu mảng nào thì bỏ qua mảng đó.\n"
    "- Không dùng markdown; không bình luận ngoài nội dung cuộc gọi.\n"
    "ĐỊNH DẠNG TRẢ LỜI (bắt buộc): CHỈ trả về phần tóm tắt thuần chữ, không bọc "
    "trong dấu ngoặc kép, không kèm nhãn hay chữ nào khác."
)


class CloudfoneError(RuntimeError):
    """Raised when the CloudFone API rejects a request or answers unusable data."""


@dataclass(frozen=True)
class CallTranscript:
    """One call row from GetCallLogs (spec 1.1) — transcript when provided."""

    call_id: str
    phone: str = ""
    direction: str = ""
    agent: str = ""
    duration_seconds: int = 0
    recorded_at: str = ""
    transcript: str = ""


@dataclass(frozen=True)
class CallInsight:
    transcript: CallTranscript
    summary: str | None = None


@dataclass(frozen=True)
class CloudfoneInsightsResult:
    status: str
    transcript_count: int = 0
    insights_count: int = 0
    provider_id: str | None = None
    error: str | None = None
    missing: list[str] = field(default_factory=list)


def _first(data: dict, *names: str, default: str = "") -> str:
    """First non-empty string among aliased provider fields (tolerant parsing)."""
    for name in names:
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and value is not None:
            return str(value)
    return default


def _parse_transcript(raw: dict) -> CallTranscript:
    """Map one CloudFone analytics row onto :class:`CallTranscript`.

    CloudFone's field naming varies across tenants/API revisions, so the row is
    read case-insensitively (and separator-insensitively: ``CallID`` and
    ``call_id`` are the same key) over the documented aliases; unknown extras
    are ignored rather than failing the whole daily fetch.
    """
    lowered = {
        key.replace("_", "").replace("-", "").lower(): value
        for key, value in raw.items()
        if isinstance(key, str)
    }
    duration_raw = lowered.get("duration") or lowered.get("callduration") or 0
    try:
        duration = int(float(duration_raw))
    except (TypeError, ValueError):
        duration = 0
    return CallTranscript(
        call_id=_first(lowered, "callid", "id", "recordingid", "sessionid"),
        phone=_first(lowered, "phone", "phonenumber", "caller", "fromnumber"),
        direction=_first(lowered, "direction", "calltype", "type"),
        agent=_first(lowered, "agent", "agentname", "extension", "user"),
        duration_seconds=duration,
        recorded_at=_first(lowered, "starttime", "startat", "createdat", "time"),
        transcript=_first(
            lowered,
            "transcript",
            "transcription",
            "content",
            "voicetranscript",
            "analysiscontent",
        ),
    )


def _data_items(payload: dict) -> list[dict]:
    """The analytics rows inside a successful CloudFone envelope."""
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("data", "items", "records", "list"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _day_window(day: date) -> tuple[str, str]:
    """The spec date window covering one full calendar day (ICT wall clock)."""
    day_str = day.isoformat()
    return f"{day_str} 00:00:01", f"{day_str} 23:59:59"


def _envelope_total(payload: dict, *, fallback: int) -> int:
    """The envelope's row count; a missing/garbage ``total`` trusts the page."""
    raw = payload.get("total")
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


class CloudfoneClient:
    """CloudFone client per the GetCallLogs spec 1.1 (API.docx, POST + JSON).

    Every request is a POST to ``{base}/{Method}`` whose JSON body carries the
    three credential fields — ``ServiceName``, ``AuthUser``, ``AuthKey`` —
    plus the call's parameters; there is no header auth and no query-string
    secret (URLs stay clean in proxy logs). GetCallLogs additionally requires
    ``Direction``, ``DateStart``, ``DateEnd``, ``PageIndex`` and ``PageSize``.
    ``transport`` replaces the HTTP call in tests; production resolves it
    through the process-scoped httpx client.
    """

    def __init__(
        self,
        service_name: str,
        auth_user: str,
        auth_key: str,
        *,
        base_url: str = CLOUDFONE_API_BASE,
        timeout: float = 30.0,
        transport: CloudfoneTransport | None = None,
    ) -> None:
        self.service_name = service_name
        self.auth_user = auth_user
        self.auth_key = auth_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport

    async def _post(self, method: str, payload: dict) -> dict:
        body = {
            "ServiceName": self.service_name,
            "AuthUser": self.auth_user,
            "AuthKey": self.auth_key,
            **payload,
        }
        if self._transport is not None:
            return await self._transport(method, body)

        import httpx

        from app.core.http import get_http_client

        client = await get_http_client(
            "cloudfone",
            base_url=self.base_url,
            timeout=self.timeout,
        )
        try:
            response = await client.post(f"/{method}", json=body)
        except httpx.HTTPError as exc:
            raise CloudfoneError(f"CloudFone không phản hồi: {exc}") from exc
        if response.status_code >= 400:
            raise CloudfoneError(f"CloudFone trả lỗi HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise CloudfoneError("CloudFone trả dữ liệu không phải JSON") from exc
        return data

    async def _request(self, method: str, payload: dict) -> dict:
        data = await self._post(method, payload)
        if not isinstance(data, dict):
            raise CloudfoneError("CloudFone trả dữ liệu không phải object")
        if str(data.get("result", "")).lower() != "success":
            message = _first(data, "message", "error", "error_message")
            raise CloudfoneError(f"CloudFone từ chối yêu cầu: {message or 'không rõ lý do'}")
        return data

    async def get_call_logs(
        self,
        *,
        date_start: str | None = None,
        date_end: str | None = None,
        direction: str = DEFAULT_DIRECTION,
        page_index: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict]:
        """One GetCallLogs page — the spec-1.1 credential probe.

        The date window defaults to yesterday → today (ICT full days); the
        caller may pass an explicit ``YYYY-MM-DD HH:MM:SS`` window instead.
        Only required spec fields ride along: ``Direction``, ``DateStart``,
        ``DateEnd``, ``PageIndex``, ``PageSize``.
        """
        if not (date_start and date_end):
            today = datetime.now(ICT).date()
            default_start, default_end = _day_window(today - timedelta(days=1)), _day_window(today)
            date_start = date_start or default_start[0]
            date_end = date_end or default_end[1]
        data = await self._request(
            "GetCallLogs",
            {
                "Direction": direction,
                "DateStart": date_start,
                "DateEnd": date_end,
                "PageIndex": max(int(page_index), 0),
                "PageSize": max(int(page_size), 1),
            },
        )
        return _data_items(data)

    async def fetch_daily_transcripts(self, *, day: date) -> list[CallTranscript]:
        """The analyzed voice rows of one full ICT calendar day.

        Spec paging: the day's window ``00:00:01 → 23:59:59``, oldest-first
        (``IsSort=1``), 200 rows per page, walking pages until the envelope's
        ``total`` is drained — bounded at :data:`MAX_DAILY_PAGES` so a broken
        counter can never loop forever (a bound of 5 × 200 rows covers any
        real day; past it the tick logs a truncation warning and ships what
        it has).
        """
        date_start, date_end = _day_window(day)
        rows: list[dict] = []
        total: int | None = None
        for page_index in range(MAX_DAILY_PAGES):
            data = await self._request(
                "GetCallLogs",
                {
                    "Direction": DEFAULT_DIRECTION,
                    "DateStart": date_start,
                    "DateEnd": date_end,
                    "PageIndex": page_index,
                    "PageSize": DEFAULT_PAGE_SIZE,
                    "IsSort": 1,
                },
            )
            items = _data_items(data)
            rows.extend(items)
            total = _envelope_total(data, fallback=len(rows))
            if not items or len(rows) >= total:
                break
        if total is not None and len(rows) < total:
            logger.warning(
                "cloudfone daily fetch truncated: %d/%d rows after %d pages",
                len(rows),
                total,
                MAX_DAILY_PAGES,
            )
        return [_parse_transcript(item) for item in rows]


def insights_window(now: datetime) -> date:
    """The previous full ICT calendar day the tick reports on."""
    return (now or datetime.now(timezone.utc)).astimezone(ICT).date() - timedelta(days=1)


def insights_subject(day: date) -> str:
    return f"Cloudfone — Phân tích cuộc gọi ngày {day.strftime('%d/%m/%Y')}"


async def build_insights(
    transcripts: list[CallTranscript],
    summarizer: Callable[[str, str], Awaitable[str]] | None,
) -> list[CallInsight]:
    """Summarize each transcript through the LLM, fail-soft per call.

    One dead provider leaves that call's summary empty and the rest of the
    letter — and the send — intact, mirroring the digest's enrichment rule: a
    late/partial summary is worth more than no email at all.
    """
    insights: list[CallInsight] = []
    for item in transcripts:
        summary: str | None = None
        if summarizer is not None and item.transcript:
            try:
                reply = await summarizer(
                    INSIGHTS_SYSTEM_PROMPT,
                    "BẢN GHI CUỘC GỌI:\n" + item.transcript[:6000],
                )
                summary = (reply or "").strip() or None
            except Exception:  # noqa: BLE001 — a summary failure must not block the email
                logger.warning(
                    "cloudfone insights summary failed call_id=%s", item.call_id, exc_info=True
                )
        insights.append(CallInsight(transcript=item, summary=summary))
    return insights


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _fmt_duration(seconds: int) -> str:
    minutes, sec = divmod(max(int(seconds), 0), 60)
    return f"{minutes}p{sec:02d}s" if minutes else f"{sec}s"


def render_insights_html(insights: list[CallInsight], day: date) -> str:
    """The plain-HTML daily letter: overview stats + one block per call."""
    total = len(insights)
    with_transcript = sum(1 for i in insights if i.transcript.transcript)
    rows: list[str] = []
    for insight in insights:
        call = insight.transcript
        summary = insight.summary or "(Không có tóm tắt — transcript trống hoặc LLM lỗi.)"
        meta = " · ".join(
            part
            for part in (
                _escape(call.phone or "—"),
                _escape(call.direction or "—"),
                _escape(call.agent or "—"),
                _fmt_duration(call.duration_seconds),
                _escape(call.recorded_at or ""),
            )
            if part
        )
        rows.append(
            '<div style="margin:0 0 16px 0;padding:12px;border:1px solid #e2e8f0;'
            'border-radius:8px">'
            f'<p style="margin:0 0 4px 0;font-size:12px;color:#64748b">{meta}</p>'
            f'<p style="margin:0 0 8px 0;font-weight:600">{_escape(summary)}</p>'
            f'<details><summary style="color:#64748b;font-size:12px">Transcript</summary>'
            f'<p style="white-space:pre-wrap;font-size:12px">{_escape(call.transcript)}</p>'
            "</details></div>"
        )
    return (
        '<div style="font-family:sans-serif;max-width:640px">'
        f"<h2>Cloudfone — Phân tích cuộc gọi ngày {day.strftime('%d/%m/%Y')}</h2>"
        f"<p>Tổng số cuộc gọi: <b>{total}</b> · Có transcript: <b>{with_transcript}</b></p>"
        + ("".join(rows) if rows else "<p>Không có cuộc gọi nào trong ngày.</p>")
        + "</div>"
    )


async def _default_fetcher(client: CloudfoneClient, day: date) -> list[CallTranscript]:
    return await client.fetch_daily_transcripts(day=day)


async def run_cloudfone_insights(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    settings_service: IntegrationSettingsService | None = None,
    summarizer: Callable[[str, str], Awaitable[str]] | None = None,
    client: CloudfoneClient | None = None,
    fetcher: Callable[[date], Awaitable[list[CallTranscript]]] | None = None,
    sender: Callable[..., Awaitable[str | None]] | None = None,
) -> CloudfoneInsightsResult:
    """One Cloudfone insights pass: fetch yesterday → summarize → email recipients.

    ``fetcher`` and ``sender`` are injectable seams (the worker and tests pass
    fakes); production resolves the real CloudFone client from the stored key
    and sends through the shared Resend sender with the digest's from-address.
    """
    moment = now or datetime.now(timezone.utc)
    service = settings_service or IntegrationSettingsService(db)
    cfg = await service.resolve_cloudfone()

    if not cfg.enabled or not cfg.recipients:
        # The admin's off switch, or nowhere to send to: no-op without error.
        missing = [] if cfg.recipients else ["recipients"]
        return CloudfoneInsightsResult(status=STATUS_DISABLED, missing=missing)
    # Spec 1.1 auth: all three credential fields are required by GetCallLogs.
    missing_creds = [
        name
        for name, value in (
            ("service_name", cfg.service_name),
            ("auth_user", cfg.auth_user),
            ("auth_key", cfg.auth_key),
        )
        if not value
    ]
    if missing_creds:
        return CloudfoneInsightsResult(status=STATUS_UNCONFIGURED, missing=missing_creds)

    # The email rides the same Resend account as the candidate digest (one
    # sender account per deployment); without it there is nowhere to deliver.
    digest_cfg = await service.resolve_email_digest()
    if not digest_cfg.resend_api_key:
        return CloudfoneInsightsResult(status=STATUS_DISABLED, missing=["resend_api_key"])

    day = insights_window(moment)
    cloudfone_client = client or CloudfoneClient(
        cfg.service_name, cfg.auth_user, cfg.auth_key, timeout=30.0
    )
    fetch = fetcher or (lambda d: _default_fetcher(cloudfone_client, d))
    try:
        transcripts = await fetch(day)
    except CloudfoneError as exc:
        logger.warning("cloudfone insights fetch failed: %s", exc)
        return CloudfoneInsightsResult(status=STATUS_UNCONFIGURED, error=str(exc))

    if not transcripts:
        return CloudfoneInsightsResult(status=STATUS_EMPTY)

    insights = await build_insights(transcripts, summarizer)
    send = sender or send_email_via_resend
    try:
        provider_id = await send(
            api_key=digest_cfg.resend_api_key,
            from_email=DIGEST_FROM_EMAIL,
            to=list(cfg.recipients),
            subject=insights_subject(day),
            html=render_insights_html(insights, day),
        )
    except EmailDeliveryError as exc:
        logger.warning("cloudfone insights email rejected: %s", exc)
        return CloudfoneInsightsResult(
            status=STATUS_UNCONFIGURED,
            transcript_count=len(transcripts),
            insights_count=len(insights),
            error=str(exc),
        )

    logger.info(
        "cloudfone insights sent: day=%s calls=%d recipients=%d provider_id=%s",
        day.isoformat(),
        len(insights),
        len(cfg.recipients),
        provider_id or "-",
    )
    return CloudfoneInsightsResult(
        status=STATUS_SENT,
        transcript_count=len(transcripts),
        insights_count=len(insights),
        provider_id=provider_id,
    )
