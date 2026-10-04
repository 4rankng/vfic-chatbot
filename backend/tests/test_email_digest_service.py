"""Candidate digest pipeline: schedule gating, run statuses, rendering.

Service-level tests double the collector and the Resend sender (monkeypatched
on the service module); the renderer is exercised as the pure function it is.
"""

# pyright: reportArgumentType=false

from datetime import datetime, timezone

from app.services.email_digest import service as digest_module
from app.services.email_digest.repository import DigestCandidate
from app.services.email_digest.spreadsheet import XLSX_CONTENT_TYPE
from app.services.email_digest.service import (
    STATUS_DISABLED,
    STATUS_EMPTY,
    STATUS_NOT_DUE,
    STATUS_SENT,
    STATUS_UNCONFIGURED,
    is_due,
    run_digest,
    send_test_digest,
)
from app.services.integration_settings.providers.email_digest import (
    EmailDigestRuntimeConfig,
)


class _SettingsSvc:
    def __init__(self, config: EmailDigestRuntimeConfig) -> None:
        self._config = config

    async def resolve_email_digest(self) -> EmailDigestRuntimeConfig:
        return self._config


class _StateDb:
    """Narrow stub for the send-state row upsert (get/add/commit)."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.commit_count = 0

    async def get(self, _model, key):
        return self.rows.get(key)

    def add(self, row) -> None:
        self.rows[row.key] = row

    async def commit(self) -> None:
        self.commit_count += 1


def _config(**overrides) -> EmailDigestRuntimeConfig:
    values: dict = {"resend_api_key": "key", "recipients": ("a@x.vn",)}
    values.update(overrides)
    return EmailDigestRuntimeConfig(**values)


def _candidate(**overrides) -> DigestCandidate:
    values: dict = {
        "lead_id": 1,
        "name": "Test",
        "phone": "09",
        "channel_label": "Zalo Chatbot",
    }
    values.update(overrides)
    return DigestCandidate(**values)


# ── is_due (pure) ────────────────────────────────────────────────────────────


def test_not_due_before_scheduled_time():
    # 08:30 ICT < 09:00 ICT scheduled.
    now = datetime(2026, 10, 5, 1, 30, tzinfo=timezone.utc)
    assert is_due(_config(), now=now) is False


def test_due_after_scheduled_time_when_never_sent():
    now = datetime(2026, 10, 5, 2, 15, tzinfo=timezone.utc)  # 09:15 ICT
    assert is_due(_config(), now=now) is True


def test_due_is_catch_up_when_tick_misses_the_moment():
    now = datetime(2026, 10, 5, 6, 5, tzinfo=timezone.utc)  # 13:05 ICT, unsent
    assert is_due(_config(), now=now) is True


def test_not_due_when_period_already_sent():
    sent_today = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)  # 09:00 ICT today
    now = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
    assert is_due(_config(last_sent_at=sent_today), now=now) is False


def test_due_again_next_day():
    sent_yesterday = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)
    now = datetime(2026, 10, 6, 2, 5, tzinfo=timezone.utc)
    assert is_due(_config(last_sent_at=sent_yesterday), now=now) is True


def test_weekly_not_due_same_iso_week():
    sent_monday = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)  # Mon 09:00 ICT
    now_friday = datetime(2026, 10, 10, 2, 5, tzinfo=timezone.utc)
    config = _config(frequency="weekly", last_sent_at=sent_monday)
    assert is_due(config, now=now_friday) is False


def test_weekly_due_again_next_iso_week():
    sent_monday = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)
    next_monday = datetime(2026, 10, 13, 2, 5, tzinfo=timezone.utc)
    config = _config(frequency="weekly", last_sent_at=sent_monday)
    assert is_due(config, now=next_monday) is True


# ── run_digest statuses ──────────────────────────────────────────────────────


async def test_run_digest_disabled_without_recipients():
    result = await run_digest(
        _StateDb(), settings_service=_SettingsSvc(_config(recipients=()))
    )
    assert result.status == STATUS_DISABLED
    assert result.candidate_count == 0


async def test_run_digest_unconfigured_without_key(monkeypatch):
    result = await run_digest(
        _StateDb(), settings_service=_SettingsSvc(_config(resend_api_key=""))
    )
    assert result.status == STATUS_UNCONFIGURED


async def test_run_digest_not_due(monkeypatch):
    now = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)  # 08:00 ICT
    result = await run_digest(
        _StateDb(), settings_service=_SettingsSvc(_config()), now=now
    )
    assert result.status == STATUS_NOT_DUE


async def test_run_digest_empty_window(monkeypatch):
    async def fake_collect(db, *, window_start, window_end):
        return []

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    sends: list = []

    async def fail_send(**kwargs):
        sends.append(kwargs)
        raise AssertionError("must not send on an empty window")

    monkeypatch.setattr(digest_module, "send_email_via_resend", fail_send)
    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(_StateDb(), settings_service=_SettingsSvc(_config()), now=now)
    assert result.status == STATUS_EMPTY
    assert sends == []


async def test_run_digest_sends_and_advances_state(monkeypatch):
    async def fake_collect(db, *, window_start, window_end):
        assert window_start is not None
        return [_candidate()]

    async def fake_send(**kwargs):
        assert "Danh sách ứng viên mới" in kwargs["subject"]
        assert "1 ứng viên mới" in kwargs["html"]  # the letter announces the count
        (attachment,) = kwargs["attachments"]
        assert attachment.filename == "danh_sach_ung_vien_05-10-2026.xlsx"
        assert attachment.content_type == XLSX_CONTENT_TYPE
        assert attachment.content[:2] == b"PK"  # a real zip archive
        return "pid-1"

    async def fake_summary(candidate, extractor=None):
        return "Tóm tắt mẫu."

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "_candidate_summary", fake_summary)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)

    db = _StateDb()
    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(db, settings_service=_SettingsSvc(_config()), now=now)
    assert result.status == STATUS_SENT
    assert result.candidate_count == 1
    assert result.provider_id == "pid-1"
    assert db.commit_count == 1  # state advanced on success only


# ── send_test_digest ─────────────────────────────────────────────────────────


async def test_test_send_reports_missing_config():
    """The typed preview address replaces the recipient-list requirement."""
    result = await send_test_digest(
        None,
        to_email="xem.truoc@congty.vn",
        settings_service=_SettingsSvc(_config(resend_api_key="")),
    )
    assert result.ok is False
    assert result.configured is False
    assert result.missing == ["resend_api_key"]


async def test_test_send_previews_real_window_to_typed_address(monkeypatch):
    """The preview is byte-for-byte what recipients get — real pending
    window, real subject/body/workbook — delivered only to the typed
    address, and it never advances the send state."""

    async def fake_collect(db, *, window_start, window_end):
        assert window_start is not None
        return [_candidate()]

    async def fake_send(**kwargs):
        assert kwargs["to"] == ["xem.truoc@congty.vn"]
        assert kwargs["subject"] == "Danh sách ứng viên mới — 1 ứng viên (05/10/2026)"
        assert "KIỂM TRA" not in kwargs["html"]
        assert "dữ liệu mẫu" not in kwargs["html"]
        (attachment,) = kwargs["attachments"]
        assert attachment.filename == "danh_sach_ung_vien_05-10-2026.xlsx"
        assert attachment.content[:2] == b"PK"
        return "test-pid"

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)
    db = _StateDb()
    result = await send_test_digest(
        db,
        to_email="xem.truoc@congty.vn",
        settings_service=_SettingsSvc(_config(enabled=False)),  # toggle ignored
        now=datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc),
    )
    assert result.ok is True
    assert result.provider_id == "test-pid"
    assert result.candidate_count == 1
    assert db.rows == {}  # a preview never marks the window as sent
    assert db.commit_count == 0


async def test_test_send_reports_provider_rejection(monkeypatch):
    from app.services.email_service import EmailDeliveryError

    async def reject_send(**kwargs):
        raise EmailDeliveryError("Resend rejected the email (status 401)")

    async def fake_collect(db, *, window_start, window_end):
        return [_candidate()]

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", reject_send)
    result = await send_test_digest(
        None,
        to_email="xem.truoc@congty.vn",
        settings_service=_SettingsSvc(_config()),
    )
    assert result.ok is False
    assert "401" in (result.error or "")


async def test_test_send_empty_window_sends_nothing(monkeypatch):
    """No pending candidates → nothing goes out; the console gets the reason."""

    async def fake_collect(db, *, window_start, window_end):
        return []

    async def fail_send(**kwargs):
        raise AssertionError("must not send on an empty window")

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fail_send)
    result = await send_test_digest(
        None,
        to_email="xem.truoc@congty.vn",
        settings_service=_SettingsSvc(_config()),
    )
    assert result.ok is False
    assert result.candidate_count == 0
    assert "Không có ứng viên mới" in (result.error or "")


# ── renderer ─────────────────────────────────────────────────────────────────


def test_renderer_letter_carries_no_candidate_rows():
    """The Excel attachment is the list; the letter must not repeat it."""
    from app.services.email_digest.renderer import render_digest_html

    candidate = DigestCandidate(
        lead_id=3,
        name="Bình",
        phone="0912345678",
        age=27,
        gender="Nam",
        living_area="Hải Phòng",
        desired_job="Công nhân",
        expected_salary="8-10 triệu",
        channel_label="VietPhap OA",
        project_name="LG Display",
        candidate_messages=("Hỏi lương", "Hỏi vị trí"),
        summary="Ứng viên hỏi lương và vị trí.",
    )
    html = render_digest_html([candidate, candidate])
    assert "Bình" not in html
    assert "0912345678" not in html
    assert "LG Display" not in html
    assert "Ứng viên hỏi lương và vị trí." not in html
    assert "Hỏi vị trí" not in html
    # …but it announces the count and points the recipient at the attachment.
    assert "Kính gửi Quý Công ty" in html
    assert "<strong>2 ứng viên mới</strong>" in html
    assert (
        "Danh sách đầy đủ của các ứng viên nằm trong file Excel đính kèm email này."
        in html
    )
    assert "Trân trọng cảm ơn Quý Công ty" in html
    assert "— không gồm TingTing OA" not in html  # never reaches customers


async def test_run_digest_without_summarizer_still_sends(monkeypatch):
    """No injected extractor → the summary column falls back to the
    candidate's verbatim messages in the workbook, and the email still goes
    out (fallback content itself is covered by the spreadsheet tests)."""

    async def fake_collect(db, *, window_start, window_end):
        return [_candidate(candidate_messages=("Hỏi lương", "Hỏi ca làm"))]

    async def fake_send(**kwargs):
        return "pid-2"

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)

    db = _StateDb()
    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(db, settings_service=_SettingsSvc(_config()), now=now)
    assert result.status == STATUS_SENT
    assert db.commit_count == 1


async def test_run_digest_skips_when_toggle_off(monkeypatch):
    """The admin's on/off switch stops the scheduled run even when fully
    configured; the test send stays available (explicit operator action)."""

    async def fail_collect(db, *, window_start, window_end):
        raise AssertionError("must not collect while the toggle is off")

    monkeypatch.setattr(digest_module, "collect_new_candidates", fail_collect)

    async def fail_send(**kwargs):
        raise AssertionError("must not send while the toggle is off")

    monkeypatch.setattr(digest_module, "send_email_via_resend", fail_send)
    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(
        _StateDb(), settings_service=_SettingsSvc(_config(enabled=False)), now=now
    )
    assert result.status == STATUS_DISABLED


# ── phone filter (the Excel is the payload) ──────────────────────────────────


async def test_run_digest_keeps_only_candidates_with_phone(monkeypatch):
    """A lead without a mobile number is not actionable — the whole digest
    (letter count, workbook rows, summary calls) covers phone-having leads."""
    summarized: list = []

    async def fake_collect(db, *, window_start, window_end):
        return [
            _candidate(lead_id=1, name="Reachable"),
            _candidate(lead_id=2, name="Blank", phone=None),
            _candidate(lead_id=3, name="Spaces", phone="   "),
        ]

    async def fake_summary(candidate, extractor=None):
        summarized.append(candidate.lead_id)
        return "Tóm tắt."

    async def fake_send(**kwargs):
        assert "1 ứng viên" in kwargs["subject"]
        assert "1 ứng viên mới" in kwargs["html"]
        assert "Blank" not in kwargs["html"] and "Spaces" not in kwargs["html"]
        (attachment,) = kwargs["attachments"]
        assert attachment.filename == "danh_sach_ung_vien_05-10-2026.xlsx"
        return "pid-3"

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "_candidate_summary", fake_summary)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)

    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(_StateDb(), settings_service=_SettingsSvc(_config()), now=now)
    assert result.status == STATUS_SENT
    assert result.candidate_count == 1
    assert summarized == [1]  # no summarizer cost on filtered-out leads


async def test_run_digest_empty_when_no_candidate_has_phone(monkeypatch):
    async def fake_collect(db, *, window_start, window_end):
        return [_candidate(lead_id=1, phone=None)]

    async def fail_send(**kwargs):
        raise AssertionError("must not send when no candidate is reachable")

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fail_send)

    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(_StateDb(), settings_service=_SettingsSvc(_config()), now=now)
    assert result.status == STATUS_EMPTY


# ── reasoning-model <think> strip ────────────────────────────────────────────


def test_strip_reasoning_removes_think_blocks():
    from app.services.email_digest.service import _strip_reasoning

    assert (
        _strip_reasoning("<think>người dùng hỏi về địa điểm</think>\n\nỨng viên hỏi địa điểm.")
        == "Ứng viên hỏi địa điểm."
    )
    assert _strip_reasoning("<THINK>abc</THINK>Kết luận.") == "Kết luận."
    assert _strip_reasoning("<think>blok chưa đóng, tất cả là suy luận") == ""
    assert _strip_reasoning("Tóm tắt sạch không thẻ.") == "Tóm tắt sạch không thẻ."
    assert _strip_reasoning("   ") == ""


async def test_all_reasoning_summary_still_sends(monkeypatch):
    """An extractor reply that is all reasoning → summary None → the send
    still goes out; the workbook's verbatim fallback carries the candidate's
    messages."""
    async def fake_collect(db, *, window_start, window_end):
        return [_candidate(candidate_messages=("Hỏi xe đưa đón",))]

    async def reasoning_extractor(_system, _user):
        return "<think>chỉ có suy luận</think>"

    async def fake_send(**kwargs):
        return "pid-4"

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)

    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(
        _StateDb(),
        settings_service=_SettingsSvc(_config()),
        now=now,
        summarizer=reasoning_extractor,
    )
    assert result.status == STATUS_SENT


# ── project-of-interest precedence (repository helper) ───────────────────────


def test_project_precedence_focus_wins_over_page_mapping():
    from app.services.email_digest.repository import _project_of_interest

    assert (
        _project_of_interest("p1", {"p1": "Rorze", "p2": "LG Display"}, ["LG Display"])
        == "Rorze"
    )


def test_project_precedence_single_page_mapping_implies_project():
    from app.services.email_digest.repository import _project_of_interest

    assert _project_of_interest(None, {"p2": "LG Display"}, ["LG Display"]) == "LG Display"


def test_project_precedence_multiple_mappings_guess_nothing():
    from app.services.email_digest.repository import _project_of_interest

    assert _project_of_interest(None, {"p2": "LG Display", "p3": "Rorze"}, []) is None
    assert _project_of_interest(None, {"p2": "LG Display", "p3": "Rorze"}, ["LG Display", "Rorze"]) is None
    assert _project_of_interest(None, {}, []) is None


# ── channel label canonicalization ───────────────────────────────────────────


def test_channel_label_canonicalizes_seeded_oa_label():
    """The Alembic-0047 seeded OA label reads like a product name in a
    customer-facing file; the digest always shows the short brand form."""
    from app.services.email_digest.repository import channel_label

    assert (
        channel_label("zalo_oa", "default:zalo_oa", "Zalo Official Account")
        == "Zalo OA"
    )
    assert channel_label("zalo_oa", "acc", "VietPhap OA") == "VietPhap OA"
    assert channel_label("facebook_messenger", "486833177846024", None) == "Messenger"
    assert channel_label("zalo_bot", "default:zalo_bot", None) == "Zalo Chatbot"
