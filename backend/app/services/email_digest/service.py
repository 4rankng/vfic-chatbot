"""Candidate email digest orchestration: window → summarize → render → send.

One ``run_digest`` pass: resolve the admin config, gate on the schedule
(ICT-based daily/weekly, catch-up if the moment passed while the worker was
down), collect the new candidates, summarize each conversation (fail-soft),
render the HTML, send through Resend, and — only on success — advance the
send-state row so the next window starts where this one ended.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

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

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
# Fallback window when nothing has ever been sent (first run).
DIGEST_FIRST_WINDOW = timedelta(days=1)

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
    "- Không suy đoán thông tin không có trong nguồn; không dùng markdown."
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


async def _candidate_summary(
    candidate: DigestCandidate,
    extractor: Callable[[str, str], Awaitable[str]] | None,
) -> str | None:
    """LLM summary of what the candidate said; None on any failure.

    The transcript is the candidate's own words only, so a candidate who never
    types the project name — the LG Display case, where they say only "yêu cầu
    bằng cấp" while the bot answers from the focused project — gave the
    summarizer nothing to name a project, and it produced a row that read
    "không có thông tin về dự án ứng viên quan tâm..." in the same row whose
    "Dự án quan tâm" column already said LG-DISPLAY. The conversation's confirmed
    focus and channel are passed as system-provided facts so the summary and the
    columns agree.

    The extractor callable is INJECTED by the caller (the worker builds it
    from the graph factories): a service must not import the graph layer, and
    without a summarizer the renderer falls back to the candidate's verbatim
    messages — the email still goes out.
    """
    if extractor is None or not candidate.candidate_messages:
        return None
    context_lines = [f"Kênh liên hệ: {candidate.channel_label or '—'}"]
    context_lines.append(
        f"Dự án ứng viên đang quan tâm: {candidate.project_name}"
        if candidate.project_name
        else "Dự án ứng viên đang quan tâm: chưa xác định"
    )
    transcript = "\n".join(f"- {line[:300]}" for line in candidate.candidate_messages)
    try:
        text = await extractor(
            SUMMARY_SYSTEM_PROMPT,
            "THÔNG TIN HỘI THOẠI (do hệ thống xác nhận):\n"
            + "\n".join(f"- {line}" for line in context_lines)
            + "\n\nLỜI CỦA ỨNG VIÊN:\n"
            + transcript,
        )
        return _strip_reasoning(text) or None
    except Exception:  # noqa: BLE001 — a summary failure must not block the email
        logger.warning(
            "email digest summary failed lead_id=%s", candidate.lead_id, exc_info=True
        )
        return None


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

    window_start = config.last_sent_at or (moment - DIGEST_FIRST_WINDOW)
    candidates = await collect_new_candidates(
        db, window_start=window_start, window_end=moment
    )
    candidates = _with_phone(candidates)
    if not candidates:
        return DigestRunResult(status=STATUS_EMPTY)

    for candidate in candidates:
        candidate.summary = await _candidate_summary(candidate, summarizer)

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
) -> TestDigestResult:
    """Console preview send: the REAL pending digest to one typed address.

    Renders and sends exactly what a scheduled run would deliver — same
    window, same subject, same body, same workbook — so the operator previews
    the letter recipients get, without advancing the send state or marking any
    lead processed. The cron toggle is ignored (explicit operator action); the
    only required config is the Resend key, since the address comes from the
    console input.
    """
    service = settings_service or IntegrationSettingsService(db)
    config = await service.resolve_email_digest()
    missing: list[str] = []
    if not config.resend_api_key:
        missing.append("resend_api_key")
    if missing:
        return TestDigestResult(ok=False, configured=False, missing=missing)

    moment = now or datetime.now(timezone.utc)
    window_start = config.last_sent_at or (moment - DIGEST_FIRST_WINDOW)
    candidates = _with_phone(
        await collect_new_candidates(
            db, window_start=window_start, window_end=moment
        )
    )
    if not candidates:
        return TestDigestResult(
            ok=False,
            configured=True,
            missing=[],
            error="Không có ứng viên mới trong kỳ gửi.",
        )

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
