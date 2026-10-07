"""Candidate digest pipeline: schedule gating, run statuses, rendering.

Service-level tests double the collector and the Resend sender (monkeypatched
on the service module); the renderer is exercised as the pure function it is.
"""

# pyright: reportArgumentType=false

from datetime import datetime, timedelta, timezone

from app.services.email_digest import service as digest_module
from app.services.email_digest.repository import DigestCandidate
from app.services.email_digest.spreadsheet import XLSX_CONTENT_TYPE
from app.services.email_digest.service import (
    STATUS_DISABLED,
    STATUS_EMPTY,
    STATUS_NOT_DUE,
    STATUS_SENT,
    STATUS_UNCONFIGURED,
    SUMMARY_SYSTEM_PROMPT,
    _candidate_reply,
    _enrich_candidates,
    _parse_reply,
    _resolve_project,
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
        # The window is the previous Vietnam calendar day (GMT+7), not a
        # rolling last_sent→now span: 00:00 yesterday → 00:00 today, ICT.
        assert window_start == datetime(2026, 10, 4, 0, 0, tzinfo=digest_module.ICT)
        assert window_end == datetime(2026, 10, 5, 0, 0, tzinfo=digest_module.ICT)
        return [_candidate()]

    async def fake_send(**kwargs):
        assert "Danh sách ứng viên mới" in kwargs["subject"]
        assert "1 ứng viên mới" in kwargs["html"]  # the letter announces the count
        (attachment,) = kwargs["attachments"]
        assert attachment.filename == "danh_sach_ung_vien_05-10-2026.xlsx"
        assert attachment.content_type == XLSX_CONTENT_TYPE
        assert attachment.content[:2] == b"PK"  # a real zip archive
        return "pid-1"

    async def fake_enrich(candidates, summarizer=None):
        return None

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "_enrich_candidates", fake_enrich)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)

    db = _StateDb()
    now = datetime(2026, 10, 5, 2, 5, tzinfo=timezone.utc)
    result = await run_digest(db, settings_service=_SettingsSvc(_config()), now=now)
    assert result.status == STATUS_SENT
    assert result.candidate_count == 1
    assert result.provider_id == "pid-1"
    assert db.commit_count == 1  # state advanced on success only


# ── _digest_window — the Vietnam calendar day (GMT+7) ──────────────────────


def test_digest_window_is_the_whole_previous_vietnam_day():
    """00:00 → 23:59 of yesterday, ICT: none of today's chatters bleed in."""
    moment = datetime(2026, 10, 6, 2, 5, tzinfo=timezone.utc)  # 09:05 ICT
    start, end = digest_module._digest_window(moment, None)
    assert start == datetime(2026, 10, 5, 0, 0, tzinfo=digest_module.ICT)
    assert end == datetime(2026, 10, 6, 0, 0, tzinfo=digest_module.ICT)
    assert end - start == timedelta(days=1)
    # The ask: GMT+7, not the server clock.
    assert start.utcoffset() == timedelta(hours=7)
    assert end.utcoffset() == timedelta(hours=7)


def test_digest_window_follows_gmt7_across_the_midnight_boundary():
    """17:00 UTC is already the next day in Vietnam — the boundary follows ICT."""
    moment = datetime(2026, 10, 5, 17, 30, tzinfo=timezone.utc)  # 00:30 ICT, 6 Oct
    start, end = digest_module._digest_window(moment, None)
    assert start == datetime(2026, 10, 5, 0, 0, tzinfo=digest_module.ICT)
    assert end == datetime(2026, 10, 6, 0, 0, tzinfo=digest_module.ICT)


def test_digest_window_catches_up_an_outage_instead_of_dropping_days():
    """Three missed sends → the window starts at the last sent day, not yesterday."""
    moment = datetime(2026, 10, 6, 2, 5, tzinfo=timezone.utc)
    last_sent = datetime(2026, 10, 3, 2, 8, tzinfo=timezone.utc)  # 09:08 ICT, 3 Oct
    start, end = digest_module._digest_window(moment, last_sent)
    assert start == datetime(2026, 10, 3, 0, 0, tzinfo=digest_module.ICT)
    assert end == datetime(2026, 10, 6, 0, 0, tzinfo=digest_module.ICT)


def test_digest_window_ignores_a_same_day_send():
    """A last_sent inside today must not move the window into today."""
    moment = datetime(2026, 10, 6, 7, 31, tzinfo=timezone.utc)  # sent today
    start, end = digest_module._digest_window(moment, moment)
    assert start == datetime(2026, 10, 5, 0, 0, tzinfo=digest_module.ICT)
    assert end == datetime(2026, 10, 6, 0, 0, tzinfo=digest_module.ICT)


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

    async def fake_enrich(candidates, summarizer=None):
        summarized.extend(c.lead_id for c in candidates)

    async def fake_send(**kwargs):
        assert "1 ứng viên" in kwargs["subject"]
        assert "1 ứng viên mới" in kwargs["html"]
        assert "Blank" not in kwargs["html"] and "Spaces" not in kwargs["html"]
        (attachment,) = kwargs["attachments"]
        assert attachment.filename == "danh_sach_ung_vien_05-10-2026.xlsx"
        return "pid-3"

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "_enrich_candidates", fake_enrich)
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


# ── the summary must agree with the columns beside it ────────────────────────


async def test_summary_input_carries_the_project_the_sheet_column_shows():
    """The LG Display regression: the column said LG-DISPLAY, the summary said
    the candidate had given no project information.

    The summarizer only ever saw the candidate's own words, and that candidate
    wrote "giờ hạn tủi tuyển dụng và yêu cầu bằng cấp" — no project name. It is
    the bot's reply, on the conversation's focused project, that establishes
    LG-DISPLAY, and the repository already resolves that into ``project_name``.
    Passing it as a system-provided fact is what makes the two agree.
    """
    seen: dict[str, str] = {}

    async def capture(system_prompt: str, user_prompt: str) -> str:
        seen["system"] = system_prompt
        seen["user"] = user_prompt
        return "Ứng viên hỏi về dự án LG Display về yêu cầu bằng cấp."

    parsed = _parse_reply(
        await _candidate_reply(
            _candidate(
                project_name="LG Display",
                channel_label="Zalo Chatbot",
                candidate_messages=("giờ hạn tủi tuyển dụng và yêu cầu bằng cấp",),
            ),
            capture,
        )
    )

    assert "LG Display" in seen["user"]
    assert "Zalo Chatbot" in seen["user"]
    assert "giờ hạn tủi tuyển dụng" in seen["user"]
    # A plain-prose reply (no JSON object) is still a usable summary.
    assert "LG Display" in parsed.summary


def test_the_summary_prompt_forbids_the_no_information_filler():
    """The sentence the sheet actually shipped, banned by name.

    "Không có thông tin về dự án ứng viên quan tâm…" reads as the bot failing to
    read a row whose neighbouring column answers the same question, so the
    recruiter stops trusting the column.
    """
    assert "không có thông tin về" in SUMMARY_SYSTEM_PROMPT.lower()
    assert "TUYỆT ĐỐI KHÔNG viết câu" in SUMMARY_SYSTEM_PROMPT


async def test_summary_input_marks_an_unknown_project_rather_than_inventing_one():
    seen: dict[str, str] = {}

    async def capture(_system: str, user_prompt: str) -> str:
        seen["user"] = user_prompt
        return "Ứng viên hỏi về chính sách xe đưa đón."

    await _candidate_reply(
        _candidate(project_name=None, candidate_messages=("xe đưa đón thế nào ạ",)),
        capture,
    )

    assert "chưa xác định" in seen["user"]


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


def test_project_precedence_lists_every_mapped_project_when_ambiguous():
    """An ambiguous channel is real information; a blank cell hid all of it.

    Migration 0054 maps the active Messenger Page to EVERY active project, so
    "guess nothing" meant this column was blank for every Messenger candidate.
    The column now names everything the channel could mean, sorted for a stable
    sheet, and the summarizer may narrow it to one.
    """
    from app.services.email_digest.repository import _project_of_interest

    assert (
        _project_of_interest(None, {"p2": "Rorze", "p3": "LG Display"}, ["Rorze", "LG Display"])
        == "LG Display, Rorze"
    )
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


# ── the preview must rehearse the real sheet (the reported defect) ────────────


def _sheet_text(workbook) -> str:
    """Every cell of the built workbook, one row per line, tabs between."""
    import zipfile

    with zipfile.ZipFile(__import__("io").BytesIO(workbook.content)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    return sheet


async def test_preview_send_fills_the_summary_column(monkeypatch):
    """The console preview produced a sheet whose "Tóm tắt hội thoại" column was
    ALWAYS empty, because ``send_test_digest`` never built a summarizer — only
    ``run_digest`` did. The operator rehearsed a sheet the real send would never
    deliver, so they could not trust their own preview.

    This is the direct regression: the preview's workbook now carries the same
    summary the scheduled send would.
    """
    async def fake_collect(db, *, window_start, window_end):
        return [_candidate(candidate_messages=("Hỏi lương và ca làm",))]

    async def summarize(_system: str, _user: str) -> str:
        return '{"project": null, "summary": "Ứng viên hỏi về lương và ca làm."}'

    sent: dict = {}

    async def fake_send(**kwargs):
        sent.update(kwargs)
        return "preview-pid"

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", fake_send)

    result = await send_test_digest(
        _StateDb(),
        to_email="xem.truoc@congty.vn",
        settings_service=_SettingsSvc(_config()),
        summarizer=summarize,
    )

    assert result.ok is True
    (attachment,) = sent["attachments"]
    assert "Ứng viên hỏi về lương và ca làm." in _sheet_text(attachment)


async def test_preview_send_without_a_summarizer_still_sends(monkeypatch):
    """No provider available is a degradation, not a failure: the operator still
    gets the sheet, with the deterministic project column and a blank summary."""

    async def fake_collect(db, *, window_start, window_end):
        return [
            _candidate(
                project_name="LG Display, Rorze",
                mapped_projects=("LG Display", "Rorze"),
                candidate_messages=("Hỏi lương",),
            )
        ]

    async def fail_send(**kwargs):
        raise AssertionError("a missing summarizer must never block the preview")

    sent: dict = {}

    async def capture_send(**kwargs):
        sent.update(kwargs)
        return "preview-pid"

    monkeypatch.setattr(digest_module, "collect_new_candidates", fake_collect)
    monkeypatch.setattr(digest_module, "send_email_via_resend", capture_send)

    result = await send_test_digest(
        _StateDb(),
        to_email="xem.truoc@congty.vn",
        settings_service=_SettingsSvc(_config()),
        summarizer=None,
    )

    assert result.ok is True
    (attachment,) = sent["attachments"]
    assert "LG Display, Rorze" in _sheet_text(attachment)
    fail_send  # referenced for intent; the send above must have been reached


# ── project narrowing: show the channel's list, let the LLM narrow it ─────────


def _ambiguous(project: str | None = None) -> DigestCandidate:
    mapped = ("LG Display", "Rorze")
    return _candidate(
        project_name=project if project is not None else "LG Display, Rorze",
        mapped_projects=mapped,
        candidate_messages=("Hỏi về lương",),
    )


def test_ambiguous_page_mapping_lists_every_project():
    """The column names everything the channel could mean rather than going blank."""
    candidate = _ambiguous()

    assert _resolve_project(candidate, None) == "LG Display, Rorze"
    assert _resolve_project(candidate, "") == "LG Display, Rorze"


def test_llm_narrows_the_project_to_one_of_the_mapped_names():
    candidate = _ambiguous()

    assert _resolve_project(candidate, "Rorze") == "Rorze"
    # Same project, written the way the sheet styles it.
    assert _resolve_project(candidate, "LG-DISPLAY") == "LG Display"


def test_llm_invented_project_is_discarded():
    """A factory the channel never mapped must never reach a recruiter."""
    candidate = _ambiguous()

    assert _resolve_project(candidate, "Samsung") == "LG Display, Rorze"
    assert _resolve_project(candidate, "Samsung") != "Samsung"


def test_focused_project_beats_the_llm_and_the_joined_list():
    """The bot established the focus from the conversation; an LLM guess — and
    the channel's own multi-mapping — must not outrank it."""
    candidate = DigestCandidate(
        lead_id=1,
        project_name="Rorze",
        mapped_projects=("LG Display", "Rorze"),
        candidate_messages=("Hỏi về lương",),
    )

    assert _resolve_project(candidate, "LG Display") == "Rorze"
    assert _resolve_project(candidate, None) == "Rorze"


def test_single_mapping_is_never_narrowed():
    candidate = _candidate(
        project_name="LG Display", mapped_projects=("LG Display",)
    )

    assert _resolve_project(candidate, "Rorze") == "LG Display"


# ── reply parsing: fail-soft, never destroy a usable summary ─────────────────


def test_json_reply_splits_summary_and_project():
    parsed = _parse_reply(
        '{"project": "Rorze", "summary": "  Ứng viên hỏi về lương.  "}'
    )

    assert parsed.summary == "Ứng viên hỏi về lương."
    assert parsed.project == "Rorze"


def test_unparseable_reply_keeps_the_prose_as_the_summary():
    """A reasoning model that ignored the JSON contract still wrote a usable
    summary; blanking that column would be worse than a missing project."""
    parsed = _parse_reply("Ứng viên hỏi về chính sách xe đưa đón.")

    assert parsed.summary == "Ứng viên hỏi về chính sách xe đưa đón."
    assert parsed.project is None


def test_malformed_json_reply_still_yields_the_summary():
    """Malformed JSON degrades to the raw text rather than to a blank cell —
    the recruiter keeps something readable and only loses the project field."""
    parsed = _parse_reply('{"summary": "hỏi lương",}')

    assert parsed.summary == '{"summary": "hỏi lương",}'
    assert parsed.project is None


def test_reasoning_blocks_are_stripped_before_json_parsing():
    parsed = _parse_reply(
        '<think>theo yêu cầu</think>{"project": null, "summary": "Ứng viên hỏi lương."}'
    )

    assert parsed.summary == "Ứng viên hỏi lương."
    assert "think" not in (parsed.summary or "")


def test_fenced_json_reply_parses():
    parsed = _parse_reply(
        '```json\n{"project": null, "summary": "Ứng viên hỏi lương."}\n```'
    )

    assert parsed.summary == "Ứng viên hỏi lương."


def test_empty_reply_parses_to_nothing():
    assert _parse_reply(None).summary is None
    assert _parse_reply("").summary is None
    assert _parse_reply("<think>chưa đóng").summary is None


def test_json_summary_containing_braces_and_quotes_survives():
    parsed = _parse_reply(
        '{"summary": "Ứng viên nói {lương} ca làm \\"sáng\\" và hỏi ca {đêm}.",'
        ' "project": null}'
    )

    assert parsed.summary == 'Ứng viên nói {lương} ca làm "sáng" và hỏi ca {đêm}.'


# ── enrichment: fail-soft, and shared by both send paths ─────────────────────


async def test_one_failing_candidate_does_not_blank_the_others(monkeypatch):
    seen: list[int] = []

    async def flaky(_system: str, user: str) -> str:
        if "xung đột" in user:
            raise RuntimeError("provider 429")
        seen.append(1)
        return '{"summary": "Ứng viên hỏi lương.", "project": null}'

    candidates = [
        _candidate(lead_id=1, candidate_messages=("Hỏi lương",)),
        _candidate(lead_id=2, candidate_messages=("xung đột dữ liệu",)),
        _candidate(lead_id=3, candidate_messages=("Hỏi ca làm",)),
    ]
    await _enrich_candidates(candidates, flaky)

    assert [c.summary for c in candidates] == [
        "Ứng viên hỏi lương.",
        None,
        "Ứng viên hỏi lương.",
    ]
    assert seen == [1, 1]


async def test_enrichment_without_a_summarizer_is_a_no_op():
    candidate = _ambiguous()
    await _enrich_candidates([candidate], None)

    assert candidate.summary is None
    assert candidate.project_name == "LG Display, Rorze"


async def test_ambiguous_candidates_receive_the_full_mapping_in_the_prompt():
    """The LLM can only narrow to a name it was given."""
    seen: dict[str, str] = {}

    async def capture(_system: str, user: str) -> str:
        seen["user"] = user
        return '{"summary": "Ứng viên hỏi về lương.", "project": "Rorze"}'

    candidate = _ambiguous()
    parsed = _parse_reply(await _candidate_reply(candidate, capture))
    candidate.project_name = _resolve_project(candidate, parsed.project)

    assert "CÁC DỰ ÁN ỨNG VIÊN CÓ THỂ QUAN TÂM: LG Display, Rorze" in seen["user"]
    assert candidate.project_name == "Rorze"


def test_the_prompt_demands_a_json_object_and_a_mapped_project_only():
    """The project field is the one place a model could invent a factory, so the
    contract pins it to the channel's own mapping."""
    assert "ĐỊNH DẠNG TRẢ LỜI" in SUMMARY_SYSTEM_PROMPT
    assert '"project"' in SUMMARY_SYSTEM_PROMPT
    assert '"summary"' in SUMMARY_SYSTEM_PROMPT
    assert "CHỈ được lấy từ danh sách" in SUMMARY_SYSTEM_PROMPT
