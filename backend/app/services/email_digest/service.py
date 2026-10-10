"""Candidate email digest orchestration: window → summarize → render → send.

One ``run_digest`` pass: resolve the admin config, gate on the schedule
(ICT-based daily/weekly, catch-up if the moment passed while the worker was
down), collect the new candidates, summarize each conversation (fail-soft),
render the HTML, send through Resend, and — only on success — advance the
send-state row so the next window starts where this one ended.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.email_digest.renderer import (
    DIGEST_FROM_EMAIL,
    digest_subject,
    render_digest_html,
)
from app.services.email_digest.repository import (
    DigestCandidate,
    collect_new_candidates,
)
from app.services.integration_settings.providers.email_digest import (
    FREQUENCY_WEEKLY,
    EmailDigestRuntimeConfig,
)
from app.services.integration_settings.service import IntegrationSettingsService
from app.services.email_digest.spreadsheet import build_lead_workbook
from app.services.email_service import EmailDeliveryError, send_email_via_resend

logger = logging.getLogger(__name__)

ICT = ZoneInfo("Asia/Ho_Chi_Minh")  # Vietnam — GMT+7, no DST

SUMMARY_SYSTEM_PROMPT = (
    "Bạn là trợ lý tóm tắt hội thoại tuyển dụng. Viết 2-4 câu tiếng Việt tóm tắt "
    "những gì ỨNG VIÊN đã nói trong hội thoại với chatbot: ứng viên hỏi về dự án nào, "
    "kinh nghiệm, mong muốn, điều kiện công việc và các câu hỏi của ứng viên.\n"
    "Nguồn thông tin gồm hai phần: (1) phần THÔNG TIN HỘI THOẠI do hệ thống cung cấp "
    "— kênh liên hệ và dự án ứng viên đang quan tâm, đây là sự thật đã được hệ thống "
    "xác nhận nên được dùng; (2) các câu ứng viên đã nói.\n"
    "QUY TẮC BẮT BUỘC:\n"
    "- TUYỆT ĐỐI KHÔNG viết câu dạng 'không có thông tin về ...', 'chưa có thông tin "
    "...' hay 'không rõ ...'. Nếu thiếu một mảnh thông tin thì chỉ bỏ qua mảng đó và "
    "tóm tắt những gì thực sự có.\n"
    "- Nếu hệ thống cho biết dự án ứng viên đang quan tâm, hãy nêu rõ dự án đó trong "
    "câu đầu tiên, kể cả khi ứng viên không tự nhắc tên dự án (ví dụ ứng viên chỉ hỏi "
    "'yêu cầu bằng cấp' thì đó là câu hỏi về dự án đó).\n"
    "- Chỉ nói ứng viên MUỐN ứng tuyển khi ứng viên đã nói rõ. Câu hỏi tìm hiểu, dự án "
    "đang được xem và lời mời của chatbot không phải là ý định ứng tuyển.\n"
    "- Không suy đoán thông tin không có trong nguồn; không dùng markdown.\n"
    "ĐỊNH DẠNG TRẢ LỜI (bắt buộc):\n"
    "- Trả về DUY NHẤT một object JSON hợp lệ, không bọc trong ``` và không kèm chữ "
    "nào khác, đúng hai khóa: \"summary\" và \"project\".\n"
    "- \"summary\": chuỗi tiếng Việt 2-4 câu tóm tắt hội thoại.\n"
    "- \"project\": tên dự án mà lời ứng viên thực sự hỏi về, CHỈ được lấy từ danh sách "
    "\"CÁC DỰ ÁN ỨNG VIÊN CÓ THỂ QUAN TÂM\" trong phần thông tin hệ thống cung cấp, và "
    "chỉ chọn khi danh sách đó có đúng một dự án mà lời ứng viên chỉ tới. Nếu không "
    "chắc chắn, đặt null. Tuyệt đối không tự đặt tên dự án không có trong danh sách."
)

# Bounded human-readable statuses for the tick log line.
STATUS_DISABLED = "disabled"  # no recipients configured
STATUS_UNCONFIGURED = "unconfigured"  # recipients set, no Resend key
STATUS_NOT_DUE = "not_due"
STATUS_EMPTY = "empty"  # due, but no new candidates in the window
STATUS_SENT = "sent"


@dataclass(frozen=True)
class DigestRunResult:
    status: str
    candidate_count: int = 0
    provider_id: str | None = None


def _period_key(ict_now: datetime, frequency: str) -> str:
    """Identity of the send period: ICT date for daily, ISO week for weekly."""
    if frequency == FREQUENCY_WEEKLY:
        iso = ict_now.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return ict_now.date().isoformat()


def is_due(config: EmailDigestRuntimeConfig, *, now: datetime) -> bool:
    """True when the digest should fire now (or catch up) for this period.

    ``>=`` against the configured ICT send time — not equality — so a worker
    that was down through the scheduled moment still sends at the next tick
    instead of skipping a whole day. The period marker then prevents a second
    send within the same day/week.
    """
    ict_now = now.astimezone(ICT)
    hour, minute = (int(part) for part in config.send_time.split(":"))
    scheduled = ict_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if ict_now < scheduled:
        return False
    if config.last_sent_at is None:
        return True
    last_ict = config.last_sent_at.astimezone(ICT)
    return _period_key(last_ict, config.frequency) != _period_key(ict_now, config.frequency)


def _digest_window(
    moment: datetime, last_sent_at: datetime | None
) -> tuple[datetime, datetime]:
    """The Vietnam calendar day this run reports on: 00:00 → 23:59 ICT (GMT+7).

    ``window_start`` is midnight of the previous ICT day and ``window_end`` is
    midnight of the current one — the whole previous day, none of today. The
    rolling ``last_sent_at → now`` span this replaces had two failure modes:
    a late or missed send shifted the next window forward and shrank it (the
    2026-10-06 digest shipped 4 rows for a day that had 19), and a same-day
    send mixed today's early chatters into yesterday's letter.

    ``window_start`` still walks back to midnight of the last sent day when an
    outage skipped whole days, so a missed day is caught up instead of
    dropped. Asia/Ho_Chi_Minh observes no DST, so the boundary is a constant
    +07:00 year-round.
    """
    today_midnight = moment.astimezone(ICT).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    window_start = today_midnight - timedelta(days=1)
    if last_sent_at is not None:
        window_start = min(
            window_start,
            last_sent_at.astimezone(ICT).replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
        )
    return window_start, today_midnight


_THINK_PAIR_RE = re.compile(
    r"<think\b[^>]*>.*?</think\b[^>]*>\s*", re.DOTALL | re.IGNORECASE
)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>.*\Z", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Remove reasoning-model ``<think>`` blocks from an extractor reply.

    Some models emit their chain-of-thought before the answer; the digest must
    never quote that to a customer. An unterminated ``<think>`` (no closing
    tag) is treated as all-reasoning: everything from the tag on is dropped.
    """
    text = _THINK_PAIR_RE.sub("", text)
    return _THINK_OPEN_RE.sub("", text).strip()


async def _candidate_reply(
    candidate: DigestCandidate,
    extractor: Callable[[str, str], Awaitable[str]] | None,
) -> str | None:
    """One LLM call for a candidate: raw reply text, or None when not asked.

    A single call returns BOTH the summary and the project decision, because a
    second call would double the latency and cost of the whole digest for no
    extra information.

    The transcript is the candidate's own words only, so a candidate who never
    types the project name — the LG Display case, where they say only "yêu cầu
    bằng cấp" while the bot answers from the focused project — gave the
    summarizer nothing to name a project, and it produced a row that read
    "không có thông tin về dự án ứng viên quan tâm..." in the same row whose
    "Dự án quan tâm" column already said LG-DISPLAY. The conversation's confirmed
    focus and channel are passed as system-provided facts so the summary and the
    columns agree.

    The extractor callable is INJECTED by the caller (the worker and the
    composition root build it): a service must not import the graph layer.
    Without a summarizer the sheet still ships, with an empty summary cell.
    """
    if extractor is None or not candidate.candidate_messages:
        return None
    context_lines = [f"Kênh liên hệ: {candidate.channel_label or '—'}"]
    single_project = _unambiguous_project(candidate)
    context_lines.append(
        f"Dự án ứng viên đang quan tâm: {single_project}"
        if single_project
        else "Dự án ứng viên đang quan tâm: chưa xác định"
    )
    if len(candidate.mapped_projects) > 1:
        context_lines.append(
            "CÁC DỰ ÁN ỨNG VIÊN CÓ THỂ QUAN TÂM: "
            + ", ".join(candidate.mapped_projects)
        )
    transcript = "\n".join(f"- {line[:300]}" for line in candidate.candidate_messages)
    return await extractor(
        SUMMARY_SYSTEM_PROMPT,
        "THÔNG TIN HỘI THOẠI (do hệ thống xác nhận):\n"
        + "\n".join(f"- {line}" for line in context_lines)
        + "\n\nLỜI CỦA ỨNG VIÊN:\n"
        + transcript,
    )


@dataclass(frozen=True)
class _DigestReply:
    """What one summarizer reply yielded, already stripped and validated."""

    summary: str | None = None
    project: str | None = None


def _first_json_object(text: str) -> str | None:
    """The first balanced ``{ … }`` span, or None.

    A stdlib scan rather than a regex: a summary may legitimately contain
    braces or quotes, and a fenced ```json reply must parse without the caller
    stripping the fence.
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _clean_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _parse_reply(reply: str | None) -> _DigestReply:
    """Split one summarizer reply into its summary and project decision.

    Fail-soft at every step. Reasoning models sometimes answer in prose despite
    the JSON contract, and that prose is still the summary the recruiter needs —
    so a reply that is not a JSON object becomes the summary verbatim rather than
    blanking a column that could have been filled. The project stays at its
    deterministic value in that case, which is the safe direction: a guessed
    factory is worse than an honest list.
    """
    text = _strip_reasoning(reply or "")
    if not text:
        return _DigestReply()
    payload = _first_json_object(text)
    if payload is not None:
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return _DigestReply(
                summary=_clean_str(parsed.get("summary")),
                project=_clean_str(parsed.get("project")),
            )
    return _DigestReply(summary=text)


def _unambiguous_project(candidate: DigestCandidate) -> str | None:
    """The project the channel or bot already agreed on, when there is one.

    ``project_name`` is a single name unless it is the joined list of an
    ambiguous mapping — so comparing against that exact join is what separates
    "the bot confirmed LG-DISPLAY" from "the Page could mean two things".
    """
    name = (candidate.project_name or "").strip()
    if not name:
        return None
    if len(candidate.mapped_projects) > 1 and name == ", ".join(candidate.mapped_projects):
        return None
    return name


def _normalize_project(text: str) -> str:
    """Loose key for project names: case, accents and hyphens are noise.

    "LG Display" and "LG-DISPLAY" are the same project; a model that echoes the
    name differently must still be matched to the channel's mapping.
    """
    decomposed = unicodedata.normalize("NFD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.casefold().replace("-", " ").split())


def _resolve_project(
    candidate: DigestCandidate, llm_project: str | None
) -> str | None:
    """The project to print, after letting the LLM narrow an ambiguous mapping.

    A confirmed single project is never overridden — the bot established it from
    the conversation, and an LLM guess must not outrank that. Only an ambiguous
    list may be narrowed, and only to a name the channel actually maps to, so
    the digest cannot invent a factory the recruiter never ran.
    """
    if _unambiguous_project(candidate) is not None:
        return candidate.project_name
    if llm_project:
        key = _normalize_project(llm_project)
        for name in candidate.mapped_projects:
            if _normalize_project(name) == key:
                return name
    return candidate.project_name


async def _enrich_candidates(
    candidates: Sequence[DigestCandidate],
    summarizer: Callable[[str, str], Awaitable[str]] | None,
    *,
    budget_seconds: float | None = None,
) -> None:
    """Fill each candidate's summary and narrow its project, in place.

    Shared by the scheduled run and the console preview. The preview promises
    the operator the sheet recipients actually get; when it skipped this step
    its summary column was blank in a way the real send never is, so the
    operator could not trust their own rehearsal.

    Fail-soft twice over. Per candidate: one dead provider leaves that row's
    summary empty and the rest of the sheet — and the send — intact. Per run:
    ``budget_seconds`` caps the whole phase, so a slow provider on a busy
    candidate day stops enriching instead of running the job into RQ's death
    penalty, which cost the 2026-10-10 digest its send entirely. The rows past
    the budget keep an empty summary and the letter still goes out.
    """
    if summarizer is None:
        return
    loop = asyncio.get_running_loop()
    deadline = None if budget_seconds is None else loop.time() + budget_seconds
    for candidate in candidates:
        if deadline is not None and loop.time() >= deadline:
            logger.warning(
                "email digest summary budget exhausted after %d/%d leads; "
                "remaining summaries left empty and the send continues",
                sum(1 for c in candidates if c.summary),
                len(candidates),
            )
            return
        try:
            reply = await _candidate_reply(candidate, summarizer)
        except Exception:  # noqa: BLE001 — a summary failure must not block the email
            logger.warning(
                "email digest summary failed lead_id=%s", candidate.lead_id, exc_info=True
            )
            continue
        parsed = _parse_reply(reply)
        candidate.summary = parsed.summary
        candidate.project_name = _resolve_project(candidate, parsed.project)


def _with_phone(candidates: list[DigestCandidate]) -> list[DigestCandidate]:
    """The Excel file is the payload: a lead without a mobile number is not
    actionable for the recipient, so the whole digest — subject count, letter,
    attachment — covers phone-having candidates only."""
    return [candidate for candidate in candidates if (candidate.phone or "").strip()]


async def run_digest(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    settings_service: IntegrationSettingsService | None = None,
    summarizer: Callable[[str, str], Awaitable[str]] | None = None,
) -> DigestRunResult:
    """One digest pass. Sends at most once per configured period."""
    moment = now or datetime.now(timezone.utc)
    service = settings_service or IntegrationSettingsService(db)
    config = await service.resolve_email_digest()

    if not config.recipients or not config.enabled:
        # No recipients, or the admin's on/off switch is off: no-op without
        # touching state. The synthetic test send ignores this gate on purpose
        # (an explicit operator action validates the pipeline either way).
        return DigestRunResult(status=STATUS_DISABLED)
    if not config.resend_api_key:
        logger.warning("email digest has recipients but no Resend API key")
        return DigestRunResult(status=STATUS_UNCONFIGURED)
    if not is_due(config, now=moment):
        return DigestRunResult(status=STATUS_NOT_DUE)

    window_start, window_end = _digest_window(moment, config.last_sent_at)
    candidates = await collect_new_candidates(
        db, window_start=window_start, window_end=window_end
    )
    candidates = _with_phone(candidates)
    if not candidates:
        return DigestRunResult(status=STATUS_EMPTY)

    await _enrich_candidates(
        candidates,
        summarizer,
        budget_seconds=float(get_settings().email_digest_enrich_budget_seconds),
    )

    ict_now = moment.astimezone(ICT)
    html = render_digest_html(candidates)
    subject = digest_subject(len(candidates), ict_date=ict_now.strftime("%d/%m/%Y"))
    workbook = build_lead_workbook(candidates, ict_date=ict_now.strftime("%d-%m-%Y"))
    provider_id = await send_email_via_resend(
        api_key=config.resend_api_key,
        from_email=DIGEST_FROM_EMAIL,
        to=list(config.recipients),
        subject=subject,
        html=html,
        attachments=(workbook,),
    )

    await _mark_sent(db, moment)
    logger.info(
        "email digest sent: candidates=%d recipients=%d provider_id=%s",
        len(candidates),
        len(config.recipients),
        provider_id or "-",
    )
    return DigestRunResult(
        status=STATUS_SENT, candidate_count=len(candidates), provider_id=provider_id
    )


async def _mark_sent(db: AsyncSession, when: datetime) -> None:
    """Advance the worker-owned send-state row (commit included)."""
    from app.models.integration import IntegrationSetting

    from app.services.integration_settings.providers.email_digest import (
        EMAIL_DIGEST_LAST_SENT_AT,
    )

    row = await db.get(IntegrationSetting, EMAIL_DIGEST_LAST_SENT_AT)
    if row is None:
        row = IntegrationSetting(
            key=EMAIL_DIGEST_LAST_SENT_AT, encrypted_value=when.isoformat(), is_secret=False
        )
        db.add(row)
    else:
        row.encrypted_value = when.isoformat()
        row.is_secret = False
    await db.commit()


@dataclass(frozen=True)
class TestDigestResult:
    ok: bool
    configured: bool
    missing: list[str]
    error: str | None = None
    provider_id: str | None = None
    candidate_count: int = 0


async def send_test_digest(
    db: AsyncSession,
    *,
    to_email: str,
    settings_service: IntegrationSettingsService | None = None,
    now: datetime | None = None,
    summarizer: Callable[[str, str], Awaitable[str]] | None = None,
) -> TestDigestResult:
    """Console preview send: the REAL pending digest to one typed address.

    Renders and sends exactly what a scheduled run would deliver — same
    window, same subject, same body, same summaries, same workbook — so the
    operator previews the letter recipients get, without advancing the send
    state or marking any lead processed. The cron toggle is ignored (explicit
    operator action); the only required config is the Resend key, since the
    address comes from the console input.

    ``summarizer`` is injected exactly as ``run_digest`` takes it, for the same
    reason: services must not build the graph layer's provider chain. Omitting
    it is a supported degradation (empty summary cells), never a failure — this
    is an operator pressing a button, not a scheduled obligation.
    """
    service = settings_service or IntegrationSettingsService(db)
    config = await service.resolve_email_digest()
    missing: list[str] = []
    if not config.resend_api_key:
        missing.append("resend_api_key")
    if missing:
        return TestDigestResult(ok=False, configured=False, missing=missing)

    moment = now or datetime.now(timezone.utc)
    window_start, window_end = _digest_window(moment, config.last_sent_at)
    candidates = _with_phone(
        await collect_new_candidates(
            db, window_start=window_start, window_end=window_end
        )
    )
    if not candidates:
        return TestDigestResult(
            ok=False,
            configured=True,
            missing=[],
            error="Không có ứng viên mới trong kỳ gửi.",
        )

    await _enrich_candidates(candidates, summarizer)

    ict_now = moment.astimezone(ICT)
    try:
        provider_id = await send_email_via_resend(
            api_key=config.resend_api_key,
            from_email=DIGEST_FROM_EMAIL,
            to=[to_email],
            subject=digest_subject(
                len(candidates), ict_date=ict_now.strftime("%d/%m/%Y")
            ),
            html=render_digest_html(candidates),
            attachments=(
                build_lead_workbook(
                    candidates, ict_date=ict_now.strftime("%d-%m-%Y")
                ),
            ),
        )
    except EmailDeliveryError as exc:
        return TestDigestResult(ok=False, configured=True, missing=[], error=str(exc))
    return TestDigestResult(
        ok=True,
        configured=True,
        missing=[],
        provider_id=provider_id,
        candidate_count=len(candidates),
    )
