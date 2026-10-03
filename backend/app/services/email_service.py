"""Outbound email helpers."""

import base64
import logging
from collections.abc import Sequence
from dataclasses import dataclass


from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Code constants — not admin-editable runtime settings.
PASSWORD_RESET_FROM_EMAIL = "TingTing <noreply@tingting.vip>"
RESEND_EMAILS_URL = "https://api.resend.com/emails"


class EmailDeliveryError(RuntimeError):
    """Raised when the email provider rejects a send request."""


@dataclass(frozen=True)
class EmailAttachment:
    """One binary email attachment (Resend takes base64-encoded content)."""

    filename: str
    content_type: str
    content: bytes


async def send_email_via_resend(
    *,
    api_key: str,
    from_email: str,
    to: list[str],
    subject: str,
    html: str,
    attachments: Sequence[EmailAttachment] = (),
) -> str | None:
    """Generic Resend send shared by the digest email (password reset keeps its
    own inline payload). Returns the provider message id, or None when Resend
    answers without one. Raises :class:`EmailDeliveryError` on rejection so the
    caller decides between surfacing (test send) and retrying (scheduled run).
    """
    if not api_key:
        raise EmailDeliveryError("RESEND_API_KEY is not configured")

    payload: dict[str, object] = {
        "from": from_email,
        "to": to,
        "subject": subject,
        "html": html,
    }
    if attachments:
        payload["attachments"] = [
            {
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "content": base64.b64encode(attachment.content).decode("ascii"),
            }
            for attachment in attachments
        ]
    # Reuse the process-scoped Resend client (Tech-Lead Directive §4). The key
    # travels per-request in the Authorization header so an admin-rotated Resend
    # key takes effect on the next send without rebuilding the client.
    from app.core.http import get_http_client

    client = await get_http_client("resend", timeout=10, settings=get_settings())
    response = await client.post(
        RESEND_EMAILS_URL, json=payload, headers={"Authorization": f"Bearer {api_key}"}
    )
    if response.status_code >= 400:
        logger.warning(
            "resend email failed status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise EmailDeliveryError(f"Resend rejected the email (status {response.status_code})")
    try:
        body = response.json()
    except ValueError:
        return None
    provider_id = body.get("id")
    return provider_id if isinstance(provider_id, str) else None


async def send_password_reset_otp(*, to_email: str, otp: str) -> str | None:
    """Send a password reset OTP through Resend.

    The sender address is a code constant (product requirement), and the
    Resend API key remains backend-only configuration.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailDeliveryError("RESEND_API_KEY is not configured")

    payload = {
        "from": PASSWORD_RESET_FROM_EMAIL,
        "to": [to_email],
        "subject": "Ting Ting — Mã khôi phục mật khẩu",
        "text": (
            f"Xin chào,\n\n"
            f"Mã khôi phục mật khẩu của bạn là: {otp}\n\n"
            f"Mã có hiệu lực trong {settings.password_reset_otp_ttl_minutes} phút. "
            "Nếu bạn không yêu cầu thao tác này, vui lòng bỏ qua email.\n\n"
            "Trân trọng,\nGiải pháp phần mềm Ting Ting"
        ),
        "html": (
            "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
            "<table width='100%' cellpadding='0' cellspacing='0' "
            "style='background:#f1f5f9;padding:40px 16px;font-family:-apple-system,"
            "BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;'>"
            "<tr><td align='center'>"
            # ── Card ──
            "<table width='100%' cellpadding='0' cellspacing='0' "
            "style='max-width:460px;background:#ffffff;border-radius:12px;"
            "overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);'>"
            # ── Brand header bar ──
            "<tr><td style='background:#0f172a;padding:20px 24px;text-align:center;'>"
            "<span style='font-size:17px;font-weight:600;color:#ffffff;"
            "letter-spacing:.3px'>Ting Ting Soft</span>"
            "<br/>"
            "<span style='font-size:11px;color:#94a3b8;letter-spacing:.2px'>"
            "Giải pháp phần mềm Ting Ting</span>"
            "</td></tr>"
            # ── Body ──
            "<tr><td style='padding:32px 24px 8px;'>"
            "<p style='margin:0 0 4px;color:#0f172a;font-size:15px;font-weight:500;'>"
            "Xin chào,</p>"
            "<p style='margin:0 0 24px;color:#475569;font-size:14px;line-height:1.6;'>"
            "Bạn vừa yêu cầu khôi phục mật khẩu cho tài khoản Ting Ting. "
            "Nhập mã xác nhận bên dưới để tiếp tục:</p>"
            "</td></tr>"
            # ── OTP code card ──
            "<tr><td align='center' style='padding:0 24px 24px;'>"
            "<table width='100%' cellpadding='0' cellspacing='0' "
            "style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;'>"
            "<tr><td style='padding:20px 16px;text-align:center;'>"
            f"<span style='font-size:36px;font-weight:700;color:#0f172a;"
            f"letter-spacing:8px;font-family:monospace,monospace'>{otp}</span>"
            "</td></tr></table>"
            "</td></tr>"
            # ── TTL notice ──
            "<tr><td align='center' style='padding:0 24px 24px;'>"
            f"<p style='margin:0;color:#64748b;font-size:13px;'>"
            f"Mã có hiệu lực trong <strong>{settings.password_reset_otp_ttl_minutes} phút</strong>"
            "</p>"
            "</td></tr>"
            # ── Security note ──
            "<tr><td style='padding:0 24px 24px;'>"
            "<p style='margin:0;padding:12px 16px;background:#fffbeb;border-radius:6px;"
            "font-size:12px;color:#92400e;line-height:1.5;'>"
            "🔒 Nếu bạn không yêu cầu khôi phục mật khẩu, vui lòng bỏ qua "
            "email này. Tài khoản của bạn vẫn an toàn.</p>"
            "</td></tr>"
            # ── Divider + Footer ──
            "<tr><td style='padding:0 24px;'>"
            "<hr style='border:none;border-top:1px solid #e2e8f0;margin:0;'/>"
            "</td></tr>"
            "<tr><td style='padding:16px 24px 24px;text-align:center;'>"
            "<p style='margin:0;color:#94a3b8;font-size:11px;'>"
            "© 2025 Ting Ting Soft. Giải pháp phần mềm Ting Ting."
            "<br/>Tất cả quyền được bảo lưu.</p>"
            "</td></tr>"
            # ── End card ──
            "</table>"
            # ── End wrapper ──
            "</td></tr></table>"
            "</body></html>"
        ),
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    # Reuse the process-scoped Resend client (Tech-Lead Directive §4). Auth
    # (Bearer) is passed per-request so a rotated Resend key takes effect on
    # the next call without rebuilding the client.
    from app.core.http import get_http_client

    client = await get_http_client("resend", timeout=10, settings=settings)
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
