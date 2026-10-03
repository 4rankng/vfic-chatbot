"""Pure HTML rendering for the candidate email digest.

No I/O and no imports from the app package beyond the candidate dataclass, so
the renderer is unit-testable without a database. The layout follows the
password-reset email's table style: a single centered card that renders
correctly in Gmail/Outlook without CSS support.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.email_digest.repository import DigestCandidate

DIGEST_FROM_EMAIL = "TingTing <noreply@tingting.vip>"

# Vietname labels for the lead fields the bot gathers. A field the bot never
# learned is OMITTED from the card entirely — the owner asked for no missing
# placeholders. Order matches the card layout.
_DETAIL_LABELS: tuple[tuple[str, str], ...] = (
    ("age", "Tuổi"),
    ("gender", "Giới tính"),
    ("living_area", "Khu vực"),
    ("address", "Địa chỉ"),
    ("desired_job", "Việc làm mong muốn"),
    ("years_experience", "Kinh nghiệm"),
    ("expected_salary", "Mức lương mong muốn"),
)

_TEST_BANNER = (
    "<tr><td style='padding:0 24px 16px;'>"
    "<p style='margin:0;padding:12px 16px;background:#fef9c3;border-radius:6px;"
    "font-size:13px;color:#854d0e;line-height:1.5;'>"
    "Đây là email <strong>KIỂM TRA</strong> cấu hình hệ thống — nội dung bên dưới là "
    "dữ liệu mẫu, vui lòng bỏ qua.</p></td></tr>"
)


def digest_subject(candidate_count: int, *, ict_date: str, test: bool = False) -> str:
    prefix = "[KIỂM TRA] " if test else ""
    return (
        f"{prefix}Danh sách ứng viên mới — {candidate_count} ứng viên ({ict_date})"
    )


def _esc(value: object) -> str:
    import html

    return html.escape(str(value), quote=True)


def render_candidate_card(candidate: DigestCandidate) -> str:
    """One candidate's summary card. Missing details are omitted, never blanked."""
    rows: list[str] = []
    name = (candidate.name or "").strip()
    # Customer-facing fallback: never expose an internal placeholder tone.
    display_name = _esc(name) if name else "Ứng viên (chưa rõ tên)"

    phone = (candidate.phone or "").strip()
    phone_line = ""
    if phone:
        phone_line = (
            "<p style='margin:0 0 10px;font-size:15px;color:#0f172a;font-weight:700;'>"
            f"Số điện thoại: "
            f"<a href='tel:{_esc(phone)}' style='color:#0f172a;text-decoration:none;'>"
            f"{_esc(phone)}</a></p>"
        )

    # Exclude-missing-details rule: no project line at all when unknown.
    project = (candidate.project_name or "").strip()
    project_line = ""
    if project:
        project_line = (
            "<p style='margin:0 0 2px;font-size:13px;color:#0f172a;'>"
            f"<strong>Dự án quan tâm:</strong> {_esc(project)}</p>"
        )

    channel = _esc(candidate.channel_label or "—")
    channel_line = (
        f"<p style='margin:0 0 8px;font-size:13px;color:#475569;'>Nguồn: {channel}</p>"
    )

    summary = (candidate.summary or "").strip()
    if not summary and candidate.candidate_messages:
        summary = _esc(" · ".join(candidate.candidate_messages[-3:]))
    elif summary:
        summary = _esc(summary)

    for attr, label in _DETAIL_LABELS:
        value = str(getattr(candidate, attr, "") or "").strip()
        if not value:
            continue
        rows.append(
            f"<tr><td style='padding:2px 0;color:#64748b;font-size:13px;width:42%;'>"
            f"{_esc(label)}</td>"
            f"<td style='padding:2px 0;color:#0f172a;font-size:13px;'>{_esc(value)}</td></tr>"
        )

    return f"""
<table width='100%' cellpadding='0' cellspacing='0' style='margin:0 0 16px;
background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;'>
  <tr><td style='padding:16px 20px 6px;'>
    <p style='margin:0 0 4px;font-size:16px;font-weight:600;color:#0f172a;'>{display_name}</p>
    {phone_line}
    {project_line}
    {channel_line}
    <table width='100%' cellpadding='0' cellspacing='0'>{"".join(rows)}</table>
  </td></tr>
  <tr><td style='padding:0 20px 16px;'>
    <p style='margin:0;padding:10px 14px;background:#f8fafc;border-radius:8px;
font-size:13px;color:#334155;line-height:1.55;'><strong>Tóm tắt hội thoại:</strong> {summary}</p>
  </td></tr>
</table>"""


def render_digest_html(
    candidates: Sequence[DigestCandidate],
    *,
    test: bool = False,
) -> str:
    """The full digest email body. ``test=True`` renders the synthetic banner."""
    cards = "".join(render_candidate_card(candidate) for candidate in candidates)
    intro = (
        "Dưới đây là danh sách ứng viên mới mà hệ thống thu thập được:"
        if not test
        else "Đây là email kiểm tra cấu hình — nội dung bên dưới là dữ liệu mẫu:"
    )
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>
<table width='100%' cellpadding='0' cellspacing='0'
style='background:#f1f5f9;padding:40px 16px;font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Roboto,sans-serif;'>
<tr><td align='center'>
<table width='100%' cellpadding='0' cellspacing='0'
style='max-width:640px;background:#ffffff;border-radius:12px;overflow:hidden;
box-shadow:0 1px 3px rgba(0,0,0,.08);'>
  <tr><td style='background:#0f172a;padding:20px 24px;text-align:center;'>
    <span style='font-size:17px;font-weight:600;color:#ffffff;letter-spacing:.3px'>
      Ting Ting Soft</span><br/>
    <span style='font-size:11px;color:#94a3b8;letter-spacing:.2px'>
      Danh sách ứng viên mới</span>
  </td></tr>
  {"" if not test else _TEST_BANNER}
  <tr><td style='padding:24px 24px 8px;'>
    <p style='margin:0 0 16px;color:#0f172a;font-size:15px;font-weight:500;'>{intro}</p>
    {cards}
    <p style='margin:16px 0 0;color:#94a3b8;font-size:11px;text-align:center;'>
      © 2025 Ting Ting Soft. Giải pháp phần mềm Ting Ting.</p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""
