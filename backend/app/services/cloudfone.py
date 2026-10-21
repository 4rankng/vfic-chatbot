"""Cloudfone daily call insights: fetch → transcribe → summarize → email.

Cloudfone is the vendor label for the CloudFone-hosted call center (the underlying
HTTP API stays ``api.cloudfone.vn``). One ``run_cloudfone_insights`` pass: resolve
the admin config, fetch the previous full day's call legs from
``GetCallHistoryVer2``, cluster the legs into calls, download each call's
recording (``linkFile`` WAV) and transcribe it through MiniMax speech-to-text
(injected), persist each transcript to ``cloudfone_call_transcripts`` so a rerun
never repeats the download + STT cost, summarize each answered call through the
shared digest summarizer
(injected — services must not import the graph layer), let one LLM pass draft
the day-level insights over the whole dataset, and email the letter to the
admin-configured recipients through the same Resend sender the candidate digest
uses. Re-running a day is idempotent: the tick always reports on the previous
full day, no send-state row exists, and stored transcripts skip STT.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import CLOUDFONE_API_BASE
from app.services.cloudfone_transcripts import DbTranscriptStore, TranscriptStore
from app.services.email_digest.renderer import DIGEST_FROM_EMAIL
from app.services.email_service import EmailAttachment, EmailDeliveryError, send_email_via_resend
from app.services.integration_settings.service import IntegrationSettingsService
from app.services.speech_to_text import MiniMaxAsrClient

logger = logging.getLogger(__name__)

ICT = ZoneInfo("Asia/Ho_Chi_Minh")  # Vietnam — GMT+7, no DST

# Bounded human-readable statuses for the tick log line.
STATUS_DISABLED = "disabled"  # toggle off, no recipients, or no Resend key
STATUS_UNCONFIGURED = "unconfigured"  # enabled with recipients but no Cloudfone key
STATUS_EMPTY = "empty"  # fetched fine, but the previous day had no calls
STATUS_SENT = "sent"

CloudfoneTransport = Callable[[str, dict], Awaitable[dict]]

# GetCallHistoryVer2 page geometry for the daily fetch and the admin probe.
DEFAULT_PAGE_SIZE = 200
# Bounds one day's fetch at 5 × 200 rows — any real day fits; see
# fetch_daily_calls for the truncation behavior past the bound.
MAX_DAILY_PAGES = 5
# One dial-attempt episode = legs of one caller whose consecutive callDate gap
# stays within this bound: transfer legs land 0–6s apart (verified live), real
# redials are ≥31s apart (verified live).
CALL_CHAIN_GAP_SECONDS = 30.0
# Sequential STT is ~10–15s per recording; a busy day past this bound keeps the
# extra calls in stats/letter but without transcripts (one warning).
MAX_TRANSCRIPTIONS_PER_DAY = 60
# CloudFone recording downloads: pre-signed linkFile URLs serve WAV bytes.
MAX_RECORDING_BYTES = 50 * 1024 * 1024

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

DAILY_INSIGHTS_SYSTEM_PROMPT = (
    "Bạn là chuyên gia phân tích dữ liệu tổng đài. Dưới đây là dữ liệu cuộc gọi "
    "của một ngày. Hãy tự khám phá dữ liệu và nêu những phát hiện quan trọng nhất "
    "(ví dụ: xu hướng cuộc gọi nhỡ, giờ cao điểm, khách gọi lặp lại, chủ đề phổ "
    "biến, thời lượng bất thường, tín hiệu chất lượng phục vụ — chọn những gì "
    "thực sự nổi bật trong dữ liệu này). Chỉ nêu phát hiện được dữ liệu chứng "
    "minh; không bịa. Trả về 3-7 gạch đầu dòng tiếng Việt, mỗi dòng bắt đầu bằng "
    "'– ', không markdown khác, không phần mở đầu hay kết luận.\n"
    "QUY ĐỊNH BẮT BUỘC VỀ NGÔN NGỮ:\n"
    "- Sử dụng hoàn toàn tiếng Việt tự nhiên, KHÔNG dùng tiếng Anh (ví dụ: dùng 'gọi vào', 'gọi ra', "
    "'gọi lại', 'thời lượng trung bình' thay vì 'Inbound', 'Outbound', 'Callback', 'AHT', 'SLA').\n"
    "- TUYỆT ĐỐI KHÔNG nhắc đến từ 'AI'."
)


class CloudfoneError(RuntimeError):
    """Raised when the CloudFone API rejects a request or answers unusable data."""


@dataclass(frozen=True)
class CallRecord:
    """One customer call clustered from GetCallHistoryVer2 legs.

    A call spans several legs (queue leg, agent leg, ``hangup`` leg) sharing
    one ``linkFile``; :func:`group_call_legs` collapses them. ``transcript`` is
    filled from the downloaded recording via speech-to-text (empty when STT
    was skipped or failed).
    """

    call_id: str
    started_at: str = ""
    caller: str = ""
    direction: str = ""
    agent: str = ""
    status: str = ""
    talk_seconds: int = 0
    recording_url: str = ""
    transcript: str = ""


@dataclass(frozen=True)
class DailyCallStats:
    """Deterministic day totals computed from the call records (no LLM)."""

    total_calls: int
    answered_calls: int
    missed_calls: int
    answer_rate_pct: float
    avg_talk_seconds: int
    missed: tuple[tuple[str, str], ...]  # (started_at, caller) per non-answered call


@dataclass(frozen=True)
class CallInsight:
    transcript: CallRecord
    summary: str | None = None


@dataclass(frozen=True)
class CloudfoneInsightsResult:
    status: str
    transcript_count: int = 0
    insights_count: int = 0
    transcribed_count: int = 0
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


def _lowered(raw: dict) -> dict:
    """Row keys read case/separator-insensitively (``CallID`` == ``call_id``)."""
    return {
        key.replace("_", "").replace("-", "").lower(): value
        for key, value in raw.items()
        if isinstance(key, str)
    }


def _int_field(data: dict, *names: str) -> int:
    raw = _first(data, *names)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class _Leg:
    """One GetCallHistoryVer2 row before legs are clustered into calls."""

    call_date: str
    key: str
    caller: str
    receive: str
    status: str
    real_seconds: int
    link_file: str
    direction: str

    @property
    def answered(self) -> bool:
        # A ``hangup`` leg always claims ANSWERED/0 and a 0s pickup produced no
        # conversation (verified live) — neither counts as answered.
        return self.status == "ANSWERED" and self.receive != "hangup" and self.real_seconds > 0


def _leg_from_row(raw: dict) -> _Leg:
    lowered = _lowered(raw)
    return _Leg(
        call_date=_first(lowered, "calldate"),
        key=_first(lowered, "key"),
        caller=_first(lowered, "callernumber", "callername"),
        receive=_first(lowered, "receivenumber"),
        status=_first(lowered, "status"),
        real_seconds=_int_field(lowered, "realcalltime"),
        link_file=_first(lowered, "linkfile"),
        direction=_first(lowered, "typecall"),
    )


def _leg_gap_seconds(prev: _Leg, leg: _Leg) -> float | None:
    """callDate gap in seconds; ``None`` when either timestamp is unusable."""
    try:
        prev_at = datetime.fromisoformat(prev.call_date)
        leg_at = datetime.fromisoformat(leg.call_date)
    except ValueError:
        return None
    return (leg_at - prev_at).total_seconds()


def _record_for(group: list[_Leg]) -> CallRecord:
    first = group[0]
    answered = [leg for leg in group if leg.answered]
    if answered:
        status = "ANSWERED"
    elif any(leg.status == "NO ANSWER" for leg in group):
        status = "NO ANSWER"
    elif any(leg.status == "BUSY" for leg in group):
        status = "BUSY"
    else:
        status = "FAILED"
    if answered:
        best = max(answered, key=lambda leg: leg.real_seconds)
        agent = best.receive
        talk_seconds = max(leg.real_seconds for leg in answered)
    else:
        agent = first.receive
        talk_seconds = 0
    return CallRecord(
        call_id=first.key.split(".", 1)[0] or first.call_date,
        started_at=first.call_date,
        caller=first.caller,
        direction=first.direction,
        agent=agent,
        status=status,
        talk_seconds=talk_seconds,
        recording_url=next((leg.link_file for leg in group if leg.link_file), ""),
    )


def group_call_legs(rows: list[dict]) -> list[CallRecord]:
    """Cluster leg rows into calls, ordered by start time.

    Legs sorted by ``callDate`` chain into one call while the caller is the
    same (``callerNumber``, falling back to ``callerName``) and the consecutive
    gap stays within :data:`CALL_CHAIN_GAP_SECONDS`. Verified against live
    rows: transfer legs 1s apart merge, redials ≥31s apart split, and the
    ``hangup`` leg (20s later, ANSWERED/0) chains into its call without making
    it answered. ``call_id`` is the epoch before the ``.`` of the first leg's
    ``key`` (``1790848955.584-…`` → ``"1790848955"``).
    """
    legs = sorted((_leg_from_row(row) for row in rows), key=lambda leg: (leg.call_date, leg.key))
    groups: list[list[_Leg]] = []
    for leg in legs:
        previous = groups[-1][-1] if groups else None
        if previous is not None and leg.caller and leg.caller == previous.caller:
            gap = _leg_gap_seconds(previous, leg)
            if gap is not None and gap <= CALL_CHAIN_GAP_SECONDS:
                groups[-1].append(leg)
                continue
        groups.append([leg])
    return [_record_for(group) for group in groups]


def build_daily_stats(calls: list[CallRecord]) -> DailyCallStats:
    """Exact day totals; every number here is code-computed, never LLM-typed."""
    answered = [call for call in calls if call.status == "ANSWERED"]
    missed = tuple(
        sorted(
            ((call.started_at, call.caller) for call in calls if call.status != "ANSWERED"),
        )
    )
    return DailyCallStats(
        total_calls=len(calls),
        answered_calls=len(answered),
        missed_calls=len(calls) - len(answered),
        answer_rate_pct=round(len(answered) / len(calls) * 100, 1) if calls else 0.0,
        avg_talk_seconds=(
            round(sum(call.talk_seconds for call in answered) / len(answered)) if answered else 0
        ),
        missed=missed,
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
    """CloudFone client (POST + JSON, credentials in the body per the API.docx).

    Every request is a POST to ``{base}/{Method}`` whose JSON body carries the
    three credential fields — ``ServiceName``, ``AuthUser``, ``AuthKey`` —
    plus the call's parameters; there is no header auth and no query-string
    secret (URLs stay clean in proxy logs). ``transport`` replaces the HTTP
    call in tests; production resolves it through the process-scoped httpx
    client.
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

    async def _call_history_v2_page(
        self, *, day: date, page_index: int, page_size: int
    ) -> tuple[list[dict], int]:
        """One GetCallHistoryVer2 page: the rows plus the envelope's total.

        The vendor Postman body verbatim (``PageIndex`` is 1-based on this
        endpoint — verified live).
        """
        date_start, date_end = _day_window(day)
        data = await self._request(
            "GetCallHistoryVer2",
            {
                "TypeGet": 0,
                "HideFWOut": 1,
                "DateStart": date_start,
                "DateEnd": date_end,
                "IsSort": 0,
                "CallNum": "",
                "ReceiveNum": "",
                "Key": "",
                "PageIndex": max(int(page_index), 1),
                "PageSize": max(int(page_size), 1),
            },
        )
        items = _data_items(data)
        return items, _envelope_total(data, fallback=len(items))

    async def get_call_history_v2(
        self, *, day: date, page_index: int = 1, page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[dict]:
        """One GetCallHistoryVer2 page — the admin credential probe's call."""
        items, _total = await self._call_history_v2_page(
            day=day, page_index=page_index, page_size=page_size
        )
        return items

    async def fetch_daily_calls(self, *, day: date) -> list[CallRecord]:
        """All calls of one full ICT calendar day, legs clustered.

        Paging walks ``PageIndex`` 1, 2, … until the envelope's ``total`` is
        drained — bounded at :data:`MAX_DAILY_PAGES` so a broken counter can
        never loop forever (a bound of 5 × 200 rows covers any real day; past
        it the tick logs a truncation warning and ships what it has).
        """
        rows: list[dict] = []
        total = 0
        for page_index in range(1, MAX_DAILY_PAGES + 1):
            items, total = await self._call_history_v2_page(
                day=day, page_index=page_index, page_size=DEFAULT_PAGE_SIZE
            )
            rows.extend(items)
            if not items or len(rows) >= total:
                break
        if len(rows) < total:
            logger.warning(
                "cloudfone daily fetch truncated: %d/%d rows after %d pages",
                len(rows),
                total,
                MAX_DAILY_PAGES,
            )
        return group_call_legs(rows)


def insights_window(now: datetime) -> date:
    """The previous full ICT calendar day the tick reports on."""
    return (now or datetime.now(timezone.utc)).astimezone(ICT).date() - timedelta(days=1)


def insights_subject(day: date) -> str:
    return f"Cloudfone — Phân tích cuộc gọi ngày {day.strftime('%d/%m/%Y')}"


# Transient provider blips (timeout, 429/5xx) are the common failure mode; one
# delayed retry recovers most summaries without noticeably delaying the letter.
LLM_ATTEMPTS = 2
LLM_RETRY_DELAY_SECONDS = 2.0


async def _llm_with_retry(
    llm: Callable[[str, str], Awaitable[str]], system: str, user: str
) -> str:
    """Call the LLM with one bounded retry; re-raise after the last attempt."""
    for attempt in range(1, LLM_ATTEMPTS + 1):
        try:
            return await llm(system, user)
        except Exception:
            if attempt >= LLM_ATTEMPTS:
                raise
            logger.warning("cloudfone LLM attempt %d failed; retrying", attempt, exc_info=True)
            await asyncio.sleep(LLM_RETRY_DELAY_SECONDS)
    raise RuntimeError("unreachable")  # pragma: no cover


async def build_insights(
    calls: list[CallRecord],
    summarizer: Callable[[str, str], Awaitable[str]] | None,
) -> list[CallInsight]:
    """Summarize each call's transcript through the LLM, fail-soft per call.

    A transient provider blip is retried once; a persistent failure leaves
    that call's summary empty and the rest of the letter — and the send —
    intact, mirroring the digest's enrichment rule: a late/partial summary is
    worth more than no email at all.
    """
    insights: list[CallInsight] = []
    for call in calls:
        summary: str | None = None
        if summarizer is not None and call.transcript:
            try:
                reply = await _llm_with_retry(
                    summarizer,
                    INSIGHTS_SYSTEM_PROMPT,
                    "BẢN GHI CUỘC GỌI:\n" + call.transcript[:6000],
                )
                summary = _strip_thinking(reply or "") or None
            except Exception:  # noqa: BLE001 — a summary failure must not block the email
                logger.warning(
                    "cloudfone insights summary failed call_id=%s", call.call_id, exc_info=True
                )
        insights.append(CallInsight(transcript=call, summary=summary))
    return insights


async def build_daily_insights(
    stats: DailyCallStats,
    calls: list[CallRecord],
    llm: Callable[[str, str], Awaitable[str]] | None,
) -> str | None:
    """One LLM pass over the whole day: the model explores the dataset itself.

    The payload carries the code-computed stats plus one compact line per call
    (transcript excerpt included) and the system prompt asks for 3–7 grounded
    Vietnamese bullets. Empty reply or any provider failure → ``None`` and the
    letter ships without the section. Reuses the injected summarizer seam — no
    second LLM entry point.
    """
    if llm is None:
        return None
    lines = [
        f"Tổng cuộc gọi: {stats.total_calls} · Trả lời: {stats.answered_calls} "
        f"({stats.answer_rate_pct:.1f}%) · Nhỡ: {stats.missed_calls} · "
        f"Thời gian trò chuyện TB: {stats.avg_talk_seconds}s"
    ]
    for call in calls:
        excerpt = call.transcript[:200] if call.transcript else "—"
        lines.append(
            f"{_hhmm(call.started_at)} · {call.caller} · {call.direction} · "
            f"{call.agent} · {call.status} · {call.talk_seconds} · {excerpt}"
        )
    try:
        reply = await _llm_with_retry(llm, DAILY_INSIGHTS_SYSTEM_PROMPT, "\n".join(lines))
    except Exception:  # noqa: BLE001 — daily notes are optional enrichment
        logger.warning("cloudfone daily insights failed", exc_info=True)
        return None
    return _strip_thinking(reply or "") or None


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _strip_thinking(reply: str) -> str:
    """Drop reasoning-model ``<think>`` blocks — verified live that MiniMax-M2.5
    returns them inline in ``content``; the letter must never ship reasoning."""
    text = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", reply, flags=re.DOTALL)
    return text.strip()


def _fmt_duration(seconds: int) -> str:
    minutes, sec = divmod(max(int(seconds), 0), 60)
    return f"{minutes}p{sec:02d}s" if minutes else f"{sec}s"


def _hhmm(started_at: str) -> str:
    return started_at[11:16] if len(started_at) >= 16 else started_at


def _daily_note_paragraphs(notes: str) -> list[str]:
    """Each ``–``-prefixed line becomes its own <p>; other lines merge into one."""
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in notes.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("–"):
            if buffer:
                paragraphs.append(f"<p>{_escape(' '.join(buffer))}</p>")
                buffer = []
            paragraphs.append(f"<p>{_escape(stripped)}</p>")
        else:
            buffer.append(stripped)
    if buffer:
        paragraphs.append(f"<p>{_escape(' '.join(buffer))}</p>")
    return paragraphs


def render_insights_html(
    insights: list[CallInsight],
    stats: DailyCallStats,
    daily_notes: str | None,
    day: date,
) -> str:
    """The plain-HTML daily letter: stats header, missed line, day insights,
    then one block per answered call (missed calls live in the missed line)."""
    ans_pct = round(stats.answer_rate_pct, 1)
    mis_pct = round(100.0 - ans_pct, 1) if stats.total_calls > 0 else 0.0

    slots = {
        "00:00 - 08:00 (Sáng sớm)": {"ans": 0, "mis": 0},
        "08:00 - 12:00 (Sáng)": {"ans": 0, "mis": 0},
        "12:00 - 18:00 (Chiều)": {"ans": 0, "mis": 0},
        "18:00 - 24:00 (Tối)": {"ans": 0, "mis": 0},
    }
    for ins in insights:
        time_str = _hhmm(ins.transcript.started_at)
        if time_str:
            hour = int(time_str.split(":")[0]) if ":" in time_str else 9
            if hour < 8:
                slots["00:00 - 08:00 (Sáng sớm)"]["ans"] += 1
            elif hour < 12:
                slots["08:00 - 12:00 (Sáng)"]["ans"] += 1
            elif hour < 18:
                slots["12:00 - 18:00 (Chiều)"]["ans"] += 1
            else:
                slots["18:00 - 24:00 (Tối)"]["ans"] += 1
    for started_at, _ in stats.missed:
        time_str = _hhmm(started_at)
        if time_str:
            hour = int(time_str.split(":")[0]) if ":" in time_str else 9
            if hour < 8:
                slots["00:00 - 08:00 (Sáng sớm)"]["mis"] += 1
            elif hour < 12:
                slots["08:00 - 12:00 (Sáng)"]["mis"] += 1
            elif hour < 18:
                slots["12:00 - 18:00 (Chiều)"]["mis"] += 1
            else:
                slots["18:00 - 24:00 (Tối)"]["mis"] += 1

    parts = [
        '<div style="font-family:sans-serif;max-width:640px">',
        f"<h2>Cloudfone — Phân tích cuộc gọi ngày {day.strftime('%d/%m/%Y')}</h2>",
        # Visual KPI Card Table
        '<table style="width:100%;border-collapse:separate;border-spacing:6px;margin:0 0 10px 0"><tr>',
        f'<td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center;width:25%"><div style="font-size:10px;color:#64748b;font-weight:700">TỔNG GỌI</div><div style="font-size:18px;font-weight:800;color:#1e293b;margin-top:2px">{stats.total_calls}</div></td>',
        f'<td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center;width:25%"><div style="font-size:10px;color:#64748b;font-weight:700">TỶ LỆ PHỤC VỤ</div><div style="font-size:18px;font-weight:800;color:{"#16a34a" if ans_pct >= 80 else "#dc2626"};margin-top:2px">{ans_pct:.1f}%</div></td>',
        f'<td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center;width:25%"><div style="font-size:10px;color:#64748b;font-weight:700">CUỘC NHỠ</div><div style="font-size:18px;font-weight:800;color:{"#dc2626" if stats.missed_calls > 0 else "#64748b"};margin-top:2px">{stats.missed_calls}</div></td>',
        f'<td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px;text-align:center;width:25%"><div style="font-size:10px;color:#64748b;font-weight:700">THỜI LƯỢNG TB</div><div style="font-size:18px;font-weight:800;color:#1e293b;margin-top:2px">{_fmt_duration(stats.avg_talk_seconds)}</div></td>',
        "</tr></table>",
        # Segmented bar
        f'<div style="margin:0 0 12px 0;background:#f1f5f9;border-radius:4px;overflow:hidden;height:10px;display:flex">'
        f'<div style="background:#16a34a;width:{ans_pct}%;height:100%"></div>'
        f'<div style="background:#dc2626;width:{mis_pct}%;height:100%"></div>'
        f"</div>"
        if stats.total_calls > 0
        else "",
        "<p>Tổng cuộc gọi: "
        f"{stats.total_calls} · Trả lời: {stats.answered_calls} ({stats.answer_rate_pct:.1f}%) · "
        f"Nhỡ: {stats.missed_calls} · Thời gian trò chuyện TB: "
        f"{_fmt_duration(stats.avg_talk_seconds)}</p>",
    ]
    if stats.missed:
        items = "; ".join(
            f"{_hhmm(started_at)} — {_escape(caller)}" for started_at, caller in stats.missed
        )
        parts.append(f"<p>Cuộc gọi nhỡ: {items}</p>")
    if daily_notes:
        parts.extend(_daily_note_paragraphs(daily_notes))

    # Hourly distribution diagram / bar chart
    if stats.total_calls > 0:
        parts.append(
            '<div style="margin:14px 0 6px 0;font-weight:700;font-size:12px;color:#1e3a8a">📊 Phân bổ cuộc gọi theo khung giờ:</div>'
        )
        parts.append(
            '<table style="width:100%;border-collapse:collapse;margin:0 0 14px 0;font-size:11px">'
        )
        max_slot = max(max(s["ans"] + s["mis"] for s in slots.values()), 1)
        for label, s in slots.items():
            tot = s["ans"] + s["mis"]
            bar_w = int((tot / max_slot) * 100) if max_slot else 0
            ans_w = int((s["ans"] / tot) * 100) if tot else 0
            mis_w = 100 - ans_w if tot else 0
            parts.append(
                f'<tr style="border-bottom:1px solid #f1f5f9">'
                f'<td style="padding:4px 0;width:38%;color:#475569">{label}</td>'
                f'<td style="padding:4px 6px;width:44%">'
                f'<div style="background:#f1f5f9;height:10px;border-radius:2px;overflow:hidden;width:{max(bar_w, 4)}%">'
                f'<span style="display:inline-block;background:#16a34a;height:100%;width:{ans_w}%"></span>'
                f'<span style="display:inline-block;background:#dc2626;height:100%;width:{mis_w}%"></span>'
                f"</div></td>"
                f'<td style="padding:4px 0;width:18%;text-align:right;font-weight:600;color:#1e293b">{tot} cuộc ({s["ans"]}✓/{s["mis"]}✗)</td>'
                f"</tr>"
            )
        parts.append("</table>")

    rows: list[str] = []
    for insight in sorted(insights, key=lambda item: item.transcript.started_at):
        call = insight.transcript
        summary = insight.summary or "(Không có tóm tắt — transcript trống hoặc LLM lỗi.)"
        meta = " · ".join(
            part
            for part in (
                _escape(call.caller or "—"),
                _escape(call.direction or "—"),
                _escape(call.agent or "—"),
                _fmt_duration(call.talk_seconds),
                _escape(call.started_at or ""),
            )
            if part
        )
        rows.append(
            '<div style="margin:0 0 16px 0;padding:12px;border:1px solid #e2e8f0;'
            'border-radius:8px">'
            f'<p style="margin:0 0 4px 0;font-size:12px;color:#64748b">{meta}</p>'
            f'<p style="margin:0">{_escape(summary)}</p>'
            "</div>"
        )
    if rows:
        parts.append("".join(rows))
    elif stats.total_calls == 0:
        parts.append("<p>Không có cuộc gọi nào trong ngày.</p>")
    parts.append("</div>")
    return "".join(parts)


async def download_recording(url: str) -> bytes:
    """Fetch one pre-signed ``linkFile`` recording (plain GET, no auth header).

    The URL is pre-signed (verified: serves ``application/octet-stream`` WAVE
    bytes). Oversized or non-WAV payloads are rejected here so the per-call
    fail-soft path sees one clear error.
    """
    import httpx

    from app.core.http import get_http_client

    client = await get_http_client("cloudfone_recording", timeout=60.0)
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        raise CloudfoneError(f"CloudFone không phản hồi bản ghi: {exc}") from exc
    if response.status_code >= 400:
        raise CloudfoneError(f"CloudFone trả lỗi HTTP {response.status_code} cho bản ghi")
    audio = response.content
    if len(audio) > MAX_RECORDING_BYTES:
        raise CloudfoneError("Bản ghi vượt quá 50MB")
    if not (audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"):
        raise CloudfoneError("Bản ghi không phải WAV")
    return audio


async def _default_fetcher(client: CloudfoneClient, day: date) -> list[CallRecord]:
    return await client.fetch_daily_calls(day=day)


async def run_cloudfone_insights(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    settings_service: IntegrationSettingsService | None = None,
    summarizer: Callable[[str, str], Awaitable[str]] | None = None,
    client: CloudfoneClient | None = None,
    fetcher: Callable[[date], Awaitable[list[CallRecord]]] | None = None,
    transcriber: Callable[[bytes], Awaitable[str]] | None = None,
    sender: Callable[..., Awaitable[str | None]] | None = None,
    transcript_store: TranscriptStore | None = None,
) -> CloudfoneInsightsResult:
    """One Cloudfone insights pass: fetch yesterday → transcribe → summarize → email.

    ``fetcher``, ``transcriber`` and ``sender`` are injectable seams (the worker
    and tests pass fakes); production resolves the real CloudFone client from
    the stored key, transcribes through MiniMax with the admin-stored
    ``minimax_api_key`` (empty key → transcription skipped, letter intact) and
    sends through the shared Resend sender with the digest's from-address.

    ``transcript_store`` persists every transcript (``DbTranscriptStore`` on the
    caller's session by default), so a rerun or a later analysis pass reuses the
    stored text instead of re-downloading recordings and re-running STT.
    """
    moment = now or datetime.now(timezone.utc)
    service = settings_service or IntegrationSettingsService(db)
    cfg = await service.resolve_cloudfone()

    if not cfg.enabled or not cfg.recipients:
        # The admin's off switch, or nowhere to send to: no-op without error.
        missing = [] if cfg.recipients else ["recipients"]
        return CloudfoneInsightsResult(status=STATUS_DISABLED, missing=missing)
    # Auth: all three credential fields are required by the history endpoint.
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
        calls = await fetch(day)
    except CloudfoneError as exc:
        logger.warning("cloudfone insights fetch failed: %s", exc)
        return CloudfoneInsightsResult(status=STATUS_UNCONFIGURED, error=str(exc))

    if not calls:
        return CloudfoneInsightsResult(status=STATUS_EMPTY)

    transcribe = transcriber
    if transcribe is None:
        minimax = await service.resolve_minimax()
        if minimax.api_key:
            transcribe = MiniMaxAsrClient(minimax.api_key).transcribe

    store = transcript_store or (DbTranscriptStore(db) if db is not None else None)
    calls = await _attach_transcripts(calls, transcribe, store, day)
    transcribed_count = sum(1 for call in calls if call.transcript)
    answered = [call for call in calls if call.status == "ANSWERED"]
    stats = build_daily_stats(calls)
    insights = await build_insights(answered, summarizer)
    daily_notes = await build_daily_insights(stats, calls, summarizer)

    send = sender or send_email_via_resend
    from app.services.cloudfone_report import generate_daily_call_report_docx

    report_docx = generate_daily_call_report_docx(stats, calls, insights, daily_notes, day)
    attachment = EmailAttachment(
        filename=f"Bao-cao-tong-dai-{day.strftime('%Y%m%d')}.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=report_docx,
    )
    try:
        provider_id = await send(
            api_key=digest_cfg.resend_api_key,
            from_email=DIGEST_FROM_EMAIL,
            to=list(cfg.recipients),
            subject=insights_subject(day),
            html=render_insights_html(insights, stats, daily_notes, day),
            attachments=[attachment],
        )
    except EmailDeliveryError as exc:
        logger.warning("cloudfone insights email rejected: %s", exc)
        return CloudfoneInsightsResult(
            status=STATUS_UNCONFIGURED,
            transcript_count=len(answered),
            insights_count=len(insights),
            transcribed_count=transcribed_count,
            error=str(exc),
        )

    logger.info(
        "cloudfone insights sent: day=%s calls=%d stt=%d recipients=%d provider_id=%s",
        day.isoformat(),
        len(insights),
        transcribed_count,
        len(cfg.recipients),
        provider_id or "-",
    )
    return CloudfoneInsightsResult(
        status=STATUS_SENT,
        transcript_count=len(answered),
        insights_count=len(insights),
        transcribed_count=transcribed_count,
        provider_id=provider_id,
    )


async def _attach_transcripts(
    calls: list[CallRecord],
    transcriber: Callable[[bytes], Awaitable[str]] | None,
    store: TranscriptStore | None,
    day: date,
) -> list[CallRecord]:
    """Fill ``transcript`` per call from the store or its recording, fail-soft per call.

    A stored transcript (a previous pass already ran STT for that call) is reused
    as-is: no recording download, no STT. Only calls with a recording and real
    talk time are transcribed — ring-only recordings on unanswered legs are noise
    (verified). One bad recording or a dead STT provider leaves that call's
    transcript empty and the send intact.
    """
    if transcriber is None and store is None:
        return calls
    transcribed: list[CallRecord] = []
    attempts = 0
    bound_warned = False
    for call in calls:
        if not call.recording_url or call.talk_seconds <= 0:
            transcribed.append(call)
            continue
        cached = await _load_transcript(store, call.call_id)
        if cached:
            transcribed.append(replace(call, transcript=cached))
            continue
        if transcriber is None:
            transcribed.append(call)
            continue
        if attempts >= MAX_TRANSCRIPTIONS_PER_DAY:
            if not bound_warned:
                logger.warning(
                    "cloudfone insights transcribe bound reached: %d/day, "
                    "the rest of the day ships without transcripts",
                    MAX_TRANSCRIPTIONS_PER_DAY,
                )
                bound_warned = True
            transcribed.append(call)
            continue
        attempts += 1
        try:
            audio = await download_recording(call.recording_url)
            text = ((await transcriber(audio)) or "").strip()
        except Exception as exc:  # noqa: BLE001 — one bad call must not block the letter
            logger.warning("cloudfone insights transcribe failed: %s", exc)
            transcribed.append(call)
            continue
        if text:
            await _store_transcript(store, call, text, day)
        transcribed.append(replace(call, transcript=text))
    return transcribed


async def _load_transcript(store: TranscriptStore | None, call_id: str) -> str | None:
    """Best-effort cache read; a blip falls through to the STT path."""
    if store is None:
        return None
    try:
        return await store.load(call_id)
    except Exception as exc:  # noqa: BLE001 — cache failure must not block the letter
        logger.warning("cloudfone insights transcript cache read failed: %s", exc)
        return None


async def _store_transcript(
    store: TranscriptStore | None, call: CallRecord, text: str, day: date
) -> None:
    """Best-effort cache write; a blip keeps the letter and this run's text intact."""
    if store is None:
        return
    try:
        await store.save(call, text, day)
    except Exception as exc:  # noqa: BLE001 — cache failure must not block the letter
        logger.warning("cloudfone insights transcript cache write failed: %s", exc)
