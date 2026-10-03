"""Email-digest provider group: the candidate-digest email configuration.

Admin-editable from the settings console: the Resend API key (encrypted at
rest, env-fallback), the recipient list, and the send cadence. The
``email_digest_last_sent_at`` row belongs to the digest worker (send state)
and is never accepted from the admin API.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.services.audit_service import record_audit
from app.services.integration_settings._shared import _secret_status
from app.shared.domain.errors import ValidationError

logger = logging.getLogger(__name__)

EMAIL_DIGEST_RESEND_API_KEY = "email_digest_resend_api_key"
EMAIL_DIGEST_RECIPIENTS = "email_digest_recipients"
EMAIL_DIGEST_FREQUENCY = "email_digest_frequency"
EMAIL_DIGEST_SEND_TIME = "email_digest_send_time"
# Worker-owned send state. NOT admin-writable: the API never accepts it.
EMAIL_DIGEST_LAST_SENT_AT = "email_digest_last_sent_at"

EMAIL_DIGEST_SETTING_KEYS = (
    EMAIL_DIGEST_RESEND_API_KEY,
    EMAIL_DIGEST_RECIPIENTS,
    EMAIL_DIGEST_FREQUENCY,
    EMAIL_DIGEST_SEND_TIME,
    EMAIL_DIGEST_LAST_SENT_AT,
)

ADMIN_WRITABLE_KEYS = frozenset(EMAIL_DIGEST_SETTING_KEYS) - {EMAIL_DIGEST_LAST_SENT_AT}

FREQUENCY_DAILY = "daily"
FREQUENCY_WEEKLY = "weekly"
FREQUENCIES = (FREQUENCY_DAILY, FREQUENCY_WEEKLY)
DEFAULT_FREQUENCY = FREQUENCY_DAILY
# 09:00 Vietnam time (ICT) daily — the owner's default schedule. Stored as
# "HH:MM"; minutes are pinned to :00/:30 so the settings UI can offer a plain
# time select while the hourly tick catches up within its period.
DEFAULT_SEND_TIME = "09:00"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_recipients(raw: str | list[str] | None) -> list[str]:
    """Normalize a recipient list (comma/newline separated or JSON array).

    Order-preserving dedupe; empties dropped. Validation (one @, a dotted
    domain) happens here so both the API path and the renderer share one rule.
    """
    if raw is None:
        return []
    parts = (
        [part for value in raw for part in value.split(",")]
        if isinstance(raw, list)
        else raw.replace("\n", ",").split(",")
    )
    seen: list[str] = []
    for part in parts:
        email = part.strip()
        if not email:
            continue
        if not _EMAIL_RE.match(email):
            raise ValidationError(f"Email không hợp lệ: {email}")
        if email not in seen:
            seen.append(email)
    return seen


@dataclass(frozen=True)
class EmailDigestRuntimeConfig:
    resend_api_key: str = ""
    recipients: tuple[str, ...] = ()
    frequency: str = DEFAULT_FREQUENCY
    send_time: str = DEFAULT_SEND_TIME
    last_sent_at: datetime | None = None


def _parse_send_time(raw: str | None) -> str:
    """Validate the stored "HH:MM" schedule; minutes on :00/:30."""
    value = (raw or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match:
        return DEFAULT_SEND_TIME
    hour, minute = int(match.group(1)), int(match.group(2))
    if not 0 <= hour <= 23 or minute not in (0, 30):
        return DEFAULT_SEND_TIME
    return f"{hour:02d}:{minute:02d}"


def _parse_last_sent(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError:
        return None


class EmailDigestSettingsMixin:
    """Resolve/admin/persist for the candidate email digest."""

    if TYPE_CHECKING:
        # Supplied by IntegrationSettingsService, the class that mixes these in.
        # Declarations only: TYPE_CHECKING is False at runtime, so nothing here is
        # ever assigned and the composed class stays the single source of truth.
        db: AsyncSession
        settings: Settings
        cipher: IntegrationSettingsCipher

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.config import Settings
        from app.services.integration_settings.cipher import IntegrationSettingsCipher

    async def resolve_email_digest(self) -> EmailDigestRuntimeConfig:
        """Stored-first resolution with the env Resend key as fallback."""
        stored = await self._stored_values(EMAIL_DIGEST_SETTING_KEYS)
        recipients = parse_recipients(stored.get(EMAIL_DIGEST_RECIPIENTS))
        return EmailDigestRuntimeConfig(
            resend_api_key=(
                stored.get(EMAIL_DIGEST_RESEND_API_KEY) or self.settings.resend_api_key or ""
            ),
            recipients=tuple(recipients),
            frequency=stored.get(EMAIL_DIGEST_FREQUENCY) or DEFAULT_FREQUENCY,
            send_time=_parse_send_time(stored.get(EMAIL_DIGEST_SEND_TIME)),
            last_sent_at=_parse_last_sent(stored.get(EMAIL_DIGEST_LAST_SENT_AT)),
        )

    async def admin_email_digest_view(self) -> dict:
        cfg = await self.resolve_email_digest()
        return {
            "resend_api_key": _secret_status(cfg.resend_api_key),
            "recipients": list(cfg.recipients),
            "frequency": cfg.frequency,
            "send_time": cfg.send_time,
            # An empty recipient list keeps the whole feature off — there is
            # nowhere to send to, so the worker no-ops without touching state.
            "enabled": bool(cfg.recipients),
            "last_sent_at": cfg.last_sent_at.isoformat() if cfg.last_sent_at else None,
        }

    async def update_email_digest(
        self, values: dict[str, object], *, actor_id
    ) -> dict:
        """Validate + persist the admin-editable digest fields; returns the view.

        Keys outside the admin-writable set are rejected (the worker owns the
        send-state row), an unknown frequency is a validation error, and the
        key is encrypted by ``_write_setting`` like every other secret.
        """
        unknown = set(values) - ADMIN_WRITABLE_KEYS
        if unknown:
            raise ValidationError(f"Trường không hợp lệ: {', '.join(sorted(unknown))}")

        changed: list[str] = []
        api_key = values.get(EMAIL_DIGEST_RESEND_API_KEY)
        if api_key is not None and str(api_key).strip():
            await self._write_setting(
                EMAIL_DIGEST_RESEND_API_KEY,
                str(api_key),
                actor_id=actor_id,
                is_secret=True,
            )
            changed.append(EMAIL_DIGEST_RESEND_API_KEY)

        if EMAIL_DIGEST_RECIPIENTS in values:
            recipients = parse_recipients(values.get(EMAIL_DIGEST_RECIPIENTS))
            await self._write_setting(
                EMAIL_DIGEST_RECIPIENTS,
                ",".join(recipients),
                actor_id=actor_id,
                is_secret=False,
            )
            changed.append(EMAIL_DIGEST_RECIPIENTS)

        if EMAIL_DIGEST_FREQUENCY in values:
            frequency = str(values.get(EMAIL_DIGEST_FREQUENCY) or "").strip()
            if frequency not in FREQUENCIES:
                raise ValidationError(
                    f"Tần suất phải là một trong: {', '.join(FREQUENCIES)}"
                )
            await self._write_setting(
                EMAIL_DIGEST_FREQUENCY, frequency, actor_id=actor_id, is_secret=False
            )
            changed.append(EMAIL_DIGEST_FREQUENCY)

        if EMAIL_DIGEST_SEND_TIME in values:
            send_time = _parse_send_time(values.get(EMAIL_DIGEST_SEND_TIME))
            if send_time == DEFAULT_SEND_TIME and values.get(EMAIL_DIGEST_SEND_TIME) != send_time:
                # The parser silently fell back on a malformed value; surface
                # that to the operator instead of saving the default.
                raise ValidationError("Giờ gửi phải có dạng HH:MM với phút 00 hoặc 30")
            await self._write_setting(
                EMAIL_DIGEST_SEND_TIME,
                send_time,
                actor_id=actor_id,
                is_secret=False,
            )
            changed.append(EMAIL_DIGEST_SEND_TIME)

        if changed:
            await record_audit(
                self.db,
                action="update_email_digest_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="email_digest",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
        return await self.admin_email_digest_view()
