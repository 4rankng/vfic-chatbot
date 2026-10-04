"""Pure HTML rendering for the candidate email digest.

No I/O and no imports from the app package beyond the candidate dataclass, so
the renderer is unit-testable without a database. The layout mirrors the
payroll project's customer-facing statement email (``payroll_statement.html``).
The letter carries no candidate rows — the lead list lives in the Excel
attachment (``spreadsheet.py``); the email announces the count and points the
recipient at the file.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.email_digest.repository import DigestCandidate

DIGEST_FROM_EMAIL = "TingTing <noreply@tingting.vip>"

# The shared TingTing banner payroll references (payroll versions the query
# param so design updates need no code change). Verified reachable.
BANNER_URL = "https://tingting.vip/email-banner.jpg?v=20260709"

_PREHEADER = (
    "Danh sách ứng viên mới và file Excel đính kèm từ hệ thống TingTing."
)

_TEST_BANNER = (
    "<tr><td style='padding:8px 24px 0;'>"
    "<p style='margin:0;padding:12px 16px;background:#fef9c3;border-radius:6px;"
    "font-size:13px;color:#854d0e;line-height:1.5;'>"
    "Đây là email <strong>KIỂM TRA</strong> cấu hình hệ thống — file Excel "
    "đính kèm chỉ là dữ liệu mẫu, vui lòng bỏ qua.</p></td></tr>"
)


def digest_subject(candidate_count: int, *, ict_date: str, test: bool = False) -> str:
    prefix = "[KIỂM TRA] " if test else ""
    return (
        f"{prefix}Danh sách ứng viên mới — {candidate_count} ứng viên ({ict_date})"
    )


def render_digest_html(
    candidates: Sequence[DigestCandidate],
    *,
    test: bool = False,
) -> str:
    """The full digest email body, styled after the payroll statement email.

    The candidate list is deliberately NOT rendered here — the Excel
    attachment is the list. ``test=True`` renders the synthetic-sample banner
    so a configuration test never reads like a real candidate report.
    """
    count = len(candidates)
    greeting = (
        "<p style='margin:0 0 6px;color:#64748b;font-size:13px;line-height:20px;'>"
        "Kính gửi Quý Công ty,</p>"
    )
    if test:
        body = (
            "<p style='margin:0;color:#334155;font-size:15px;line-height:23px;'>"
            "Đây là email kiểm tra cấu hình hệ thống. File Excel đính kèm chỉ là "
            "dữ liệu mẫu, vui lòng bỏ qua email này.</p>"
        )
    else:
        body = (
            "<p style='margin:0;color:#334155;font-size:15px;line-height:23px;'>"
            f"Hệ thống vừa ghi nhận <strong>{count} ứng viên mới</strong>. "
            "Danh sách chi tiết gồm số điện thoại, khu vực, dự án quan tâm và "
            "tóm tắt hội thoại được đính kèm file Excel để Quý Công ty tiện "
            "theo dõi và đối chiếu.</p>"
        )
    attach_callout = (
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='width:100%;background:#eff6ff;border-left:3px solid #2563eb;"
        "border-collapse:separate;border-spacing:0;'>"
        "<tr><td style='padding:12px 14px;color:#1e3a5f;font-size:14px;line-height:22px;'>"
        "Danh sách đầy đủ của các ứng viên nằm trong file Excel đính kèm email này."
        "</td></tr></table>"
    )
    return f"""<!doctype html>
<html lang="vi">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no,date=no,address=no,email=no">
</head>
<body style="margin:0;padding:0;background:#f1f5f9;color:#172033;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
-webkit-text-size-adjust:100%;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
    {_PREHEADER}
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
style="width:100%;background:#f1f5f9;border-collapse:collapse;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="640" cellpadding="0" cellspacing="0"
style="width:100%;max-width:640px;border-collapse:separate;border-spacing:0;">
        <tr><td style="padding:0 0 12px;">
          <img src="{BANNER_URL}" alt="TingTing Soft" width="640"
style="display:block;width:100%;max-width:640px;height:auto;border:0;border-radius:16px;">
        </td></tr>
        <tr><td style="background:#ffffff;border:1px solid #dce3ed;
border-radius:12px;overflow:hidden;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
style="width:100%;border-collapse:collapse;">
            <tr><td style="padding:24px 24px 10px;">
              <p style="margin:0 0 6px;color:#2563eb;font-size:12px;line-height:18px;
font-weight:700;letter-spacing:.08em;text-transform:uppercase;">Danh sách ứng viên mới</p>
              <h1 style="margin:0;color:#0f172a;font-size:26px;line-height:32px;
font-weight:750;">Tuyển dụng TingTing</h1>
            </td></tr>
            <tr><td style="padding:4px 24px 0;">{greeting}{body}</td></tr>
            {"" if not test else _TEST_BANNER}
            <tr><td style="padding:20px 24px 0;">{attach_callout}</td></tr>
            <tr><td style="padding:22px 24px 24px;">
              <p style="margin:0;color:#475569;font-size:14px;line-height:22px;">
Trân trọng cảm ơn Quý Công ty đã hợp tác và tin tưởng sử dụng dịch vụ của TingTing.</p>
              <p style="margin:16px 0 0;color:#0f172a;font-size:14px;line-height:22px;
font-weight:700;">Dịch vụ Tuyển dụng TingTing</p>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:14px 12px 0;text-align:center;color:#64748b;
font-size:12px;line-height:18px;">Email tự động từ TingTing · Vui lòng phản hồi nếu
Quý Công ty cần hỗ trợ.</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
