"""Outbound email helpers."""
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

PASSWORD_RESET_FROM_EMAIL = "vficbot@1stop.app"
RESEND_EMAILS_URL = "https://api.resend.com/emails"


class EmailDeliveryError(RuntimeError):
    """Raised when the email provider rejects a send request."""


async def send_password_reset_otp(*, to_email: str, otp: str) -> str | None:
    """Send a password reset OTP through Resend.

    The sender is intentionally a code constant, per product requirement, and
    the Resend API key remains backend-only configuration.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailDeliveryError("RESEND_API_KEY is not configured")

    payload = {
        "from": PASSWORD_RESET_FROM_EMAIL,
        "to": [to_email],
        "subject": "VFIC password reset code",
        "text": (
            f"Your VFIC password reset code is {otp}. "
            f"It expires in {settings.password_reset_otp_ttl_minutes} minutes."
        ),
        "html": (
            "<p>Your VFIC password reset code is:</p>"
            f"<p><strong>{otp}</strong></p>"
            f"<p>This code expires in {settings.password_reset_otp_ttl_minutes} minutes.</p>"
        ),
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(RESEND_EMAILS_URL, json=payload, headers=headers)
    if response.status_code >= 400:
        logger.warning(
            "resend password reset email failed status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise EmailDeliveryError("Resend rejected password reset email")
    try:
        body = response.json()
    except ValueError:
        return None
    provider_id = body.get("id")
    return provider_id if isinstance(provider_id, str) else None
