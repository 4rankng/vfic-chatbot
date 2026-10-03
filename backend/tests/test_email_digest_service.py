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
    return DigestCandidate(
        lead_id=1,
        name="Test",
        phone="09",
        channel_label="Zalo Chatbot",
        **overrides,
    )


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
        assert "Tóm tắt hội thoại" in kwargs["html"]
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
    result = await send_test_digest(
        None, settings_service=_SettingsSvc(_config(resend_api_key="", recipients=()))
    )
    assert result.ok is False
    assert result.configured is False
    assert result.missing == ["resend_api_key", "recipients"]


async def test_test_send_sends_synthetic_sample(monkeypatch):
    async def fake_send(**kwargs):
        assert kwargs["to"] == ["a@x.vn"]
        assert "KIỂM TRA" in kwargs["subject"]
        (attachment,) = kwargs["attachments"]
        assert attachment.filename.startswith("danh_sach_ung_vien_mau_")
        assert attachment.filename.endswith(".xlsx")
        assert attachment.content[:2] == b"PK"
        return "test-pid"

    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)
    result = await send_test_digest(None, settings_service=_SettingsSvc(_config()))
    assert result.ok is True
    assert result.provider_id == "test-pid"


async def test_test_send_reports_provider_rejection(monkeypatch):
    from app.services.email_service import EmailDeliveryError

    async def reject_send(**kwargs):
        raise EmailDeliveryError("Resend rejected the email (status 401)")

    monkeypatch.setattr(digest_module, "send_email_via_resend", reject_send)
    result = await send_test_digest(None, settings_service=_SettingsSvc(_config()))
    assert result.ok is False
    assert "401" in (result.error or "")


# ── renderer ─────────────────────────────────────────────────────────────────


def test_renderer_omits_missing_fields():
    from app.services.email_digest.renderer import render_digest_html

    candidate = DigestCandidate(
        lead_id=2,
        name="Lan",
        phone=None,
        age=None,
        gender=None,
        living_area=None,
        address=None,
        desired_job=None,
        years_experience=None,
        expected_salary=None,
        channel_label="Messenger",
        project_name=None,
        candidate_messages=("Chào", "Hỏi về ca làm"),
        summary=None,
    )
    html = render_digest_html([candidate])
    assert "Chưa có tên" not in html  # name present → real name shown
    assert "Lan" in html
    assert "Tuổi" not in html  # age None → field omitted entirely
    assert "Giới tính" not in html
    assert "Khu vực" not in html
    # Project unknown → the whole line is omitted (exclude-missing-details).
    assert "Dự án quan tâm" not in html
    assert "Tóm tắt hội thoại" in html
    assert "Chào" in html  # verbatim fallback summary


def test_renderer_shows_phone_project_summary():
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
    html = render_digest_html([candidate])
    assert "0912345678" in html
    assert "LG Display" in html
    assert "Ứng viên hỏi lương và vị trí." in html
    assert "Khu vực" in html
    assert "Việc làm mong muốn" in html


def test_renderer_test_banner():
    from app.services.email_digest.renderer import render_digest_html

    html = render_digest_html([_candidate()], test=True)
    assert "KIỂM TRA" in html
    assert "dữ liệu mẫu" in html
    assert "bảng cài đặt" not in html  # no admin-console wording reaches customers


async def test_test_send_never_advances_send_state(monkeypatch):
    """A sample send validates the pipeline but marks no lead as processed."""

    async def fake_send(**kwargs):
        return "pid-test"

    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)
    db = _StateDb()
    result = await send_test_digest(db, settings_service=_SettingsSvc(_config()))
    assert result.ok is True
    # The send-state row is untouched: the next scheduled digest still covers
    # the same lead window.
    assert db.rows == {}
    assert db.commit_count == 0


async def test_run_digest_without_summarizer_falls_back_verbatim(monkeypatch):
    """No injected extractor → summary stays None; the renderer uses the
    candidate's own last messages, and the email still goes out."""

    async def fake_collect(db, *, window_start, window_end):
        return [_candidate(candidate_messages=("Hỏi lương", "Hỏi ca làm"))]

    async def fake_send(**kwargs):
        assert "Hỏi ca làm" in kwargs["html"]  # verbatim fallback present
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
