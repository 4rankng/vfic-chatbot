"""Pure unit tests for the candidate-info extraction + lead-probing pipeline.

No database, no API keys — only deterministic pure functions and simple mocks.
Matches the project convention: plain pytest, no heavy fixtures.
"""
from types import SimpleNamespace

import pytest

from app.services.lead_service import (
    _pick,
    lead_profile_text,
    normalize_integer,
    normalize_lead,
    normalize_lead_score,
    normalize_phone,
    parse_lead_json,
)
from app.services.memory_service import greeting_gate


# ---------------------------------------------------------------------------
# parse_lead_json
# ---------------------------------------------------------------------------

class TestParseLeadJson:
    def test_valid_json_dict(self):
        assert parse_lead_json({"name": "Dũng"}) == {"name": "Dũng"}

    def test_valid_json_string(self):
        assert parse_lead_json('{"name": "Dũng"}') == {"name": "Dũng"}

    def test_json_in_code_block(self):
        assert parse_lead_json("```json\n{\"name\": \"Dũng\"}\n```") == {"name": "Dũng"}

    def test_non_json_returns_empty(self):
        assert parse_lead_json("hello world") == {}

    def test_none_returns_empty(self):
        assert parse_lead_json(None) == {}

    def test_non_dict_parsed_returns_empty(self):
        assert parse_lead_json("[1, 2]") == {}

    def test_json_array_returns_empty(self):
        assert parse_lead_json('["a", "b"]') == {}


# ---------------------------------------------------------------------------
# _pick
# ---------------------------------------------------------------------------

class TestPick:
    def test_none(self):
        assert _pick(None) is None

    def test_empty_string(self):
        assert _pick("") is None

    def test_whitespace_only(self):
        assert _pick("   ") is None

    def test_strips_and_returns(self):
        assert _pick("  Dũng  ") == "Dũng"

    def test_int(self):
        assert _pick(42) == "42"


# ---------------------------------------------------------------------------
# normalize_phone
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    def test_standard_10_digit(self):
        assert normalize_phone("0987654321") == "0987654321"

    def test_plus84_prefix(self):
        assert normalize_phone("+84987654321") == "0987654321"

    def test_84_prefix(self):
        assert normalize_phone("84987654321") == "0987654321"

    def test_none(self):
        assert normalize_phone(None) is None

    def test_empty(self):
        assert normalize_phone("") is None

    def test_too_short(self):
        assert normalize_phone("0123") is None

    def test_landline_10_digit_accepted(self):
        """024 + 7 digits = 10-digit Hanoi landline — valid format."""
        assert normalize_phone("02412345678") == "02412345678"

    def test_spaces_stripped(self):
        assert normalize_phone("  098 765 4321  ") == "0987654321"

    def test_invalid_letters(self):
        assert normalize_phone("abcdefghij") is None

    def test_phone_in_sentence(self):
        assert normalize_phone("SĐT của tôi là 0357210887") == "0357210887"


# ---------------------------------------------------------------------------
# normalize_integer
# ---------------------------------------------------------------------------

class TestNormalizeInteger:
    def test_valid(self):
        assert normalize_integer("25", 15, 80) == 25

    def test_below_min(self):
        assert normalize_integer("5", 15, 80) is None

    def test_above_max(self):
        assert normalize_integer("150", 15, 80) is None

    def test_none(self):
        assert normalize_integer(None, 15, 80) is None

    def test_extracts_from_text(self):
        assert normalize_integer("tôi 30 tuổi", 15, 80) == 30


# ---------------------------------------------------------------------------
# normalize_lead_score — G4 fix: honor LLM verdict, no phone override
# ---------------------------------------------------------------------------

class TestNormalizeLeadScore:
    def test_hot_verdict_honored(self):
        assert normalize_lead_score("hot") == "hot"

    def test_warm_verdict_honored(self):
        assert normalize_lead_score("warm") == "warm"

    def test_not_interested_verdict_honored(self):
        assert normalize_lead_score("not_interested") == "not_interested"

    def test_none_returns_none(self):
        """No verdict → None (never guessed)."""
        assert normalize_lead_score(None) is None

    def test_empty_returns_none(self):
        assert normalize_lead_score("") is None

    def test_invalid_returns_none(self):
        assert normalize_lead_score("maybe") is None

    def test_no_phone_override(self):
        """The old 'return "hot" if phone else None' was removed."""
        # A valid phone number alone must NOT force a "hot" score — only the
        # LLM verdict decides.  This guards against a future regression that
        # re-introduces the phone → hot override.
        assert normalize_lead_score(None) is None
        assert normalize_lead_score("warm") == "warm"
        assert normalize_lead_score("not_interested") == "not_interested"


# ---------------------------------------------------------------------------
# normalize_lead — notes routing, latest_company→notes, full output
# ---------------------------------------------------------------------------

class TestNormalizeLead:
    def test_full_extraction(self):
        raw = '{"name": "Dũng", "phone": "0357210887", "desired_job": "công nhân", "region": "Hải Phòng"}'
        result = normalize_lead(raw, "zalo_123")
        assert result is not None
        assert result["zalo_id"] == "zalo_123"
        assert result["name"] == "Dũng"
        assert result["phone"] == "0357210887"
        assert result["desired_job"] == "công nhân"
        assert result["region"] == "Hải Phòng"
        assert result["notes"] is None

    def test_notes_extracted(self):
        raw = '{"name": "Lan", "phone": "0987654321", "notes": "xăm kín người, có xe máy"}'
        result = normalize_lead(raw, "zalo_1")
        assert result["notes"] == "xăm kín người, có xe máy"

    def test_latest_company_routed_to_notes(self):
        """Backward-compat: if old prompt still returns latest_company, route it to notes."""
        raw = '{"name": "Minh", "latest_company": "Cty TNHH Hào Quang"}'
        result = normalize_lead(raw, "zalo_1")
        assert result["latest_company"] is None  # column no longer populated
        assert result["notes"] == "Cty TNHH Hào Quang"

    def test_notes_and_latest_company_merged(self):
        """Both notes and latest_company present → joined."""
        raw = '{"notes": "có xe máy", "latest_company": "Cty TNHH Hào Quang"}'
        result = normalize_lead(raw, "zalo_1")
        assert result["notes"] == "có xe máy; Cty TNHH Hào Quang"

    def test_no_chat_id_returns_none(self):
        assert normalize_lead('{"name": "Dũng"}', None) is None

    def test_empty_chat_id_returns_none(self):
        assert normalize_lead('{"name": "Dũng"}', "") is None

    def test_invalid_json_returns_normalized_none_values(self):
        result = normalize_lead("not json at all", "zalo_1")
        assert result is not None
        assert result["name"] is None
        assert result["phone"] is None
        assert result["notes"] is None

    def test_expected_salary_passes_through(self):
        raw = '{"expected_salary": "9-11 triệu"}'
        result = normalize_lead(raw, "zalo_1")
        assert result["expected_salary"] == "9-11 triệu"


# ---------------------------------------------------------------------------
# lead_profile_text — 7-field rendering
# ---------------------------------------------------------------------------

class TestLeadProfileText:
    def test_none_lead_shows_all_missing(self):
        text = lead_profile_text(None)
        assert "mới, chưa có dữ liệu" in text
        assert "Họ tên: chưa có" in text
        assert "Số điện thoại: chưa có" in text
        assert "Công việc mong muốn: chưa có" in text
        assert "Lương mong muốn: chưa có" in text
        assert "Tỉnh / thành: chưa có" in text
        assert "Khu vực sinh sống: chưa có" in text
        assert "Ghi chú: chưa có" in text

    def test_partial_lead_shows_known_and_missing(self):
        lead = {"name": "Dũng", "phone": "0357210887", "notes": "có xe máy"}
        text = lead_profile_text(lead)
        assert "Họ tên: Dũng" in text
        assert "Số điện thoại: 0357210887" in text
        assert "Công việc mong muốn: chưa có" in text
        assert "Ghi chú: có xe máy" in text

    def test_all_fields_populated(self):
        lead = {
            "name": "Lan", "phone": "0912", "desired_job": "kho",
            "expected_salary": "8 triệu", "region": "Hải Phòng",
            "living_area": "An Lão", "notes": "xăm kín người",
        }
        text = lead_profile_text(lead)
        assert "chưa có" not in text

    def test_empty_string_value_shows_missing(self):
        lead = {"name": "", "phone": None, "desired_job": "  "}
        text = lead_profile_text(lead)
        assert "Họ tên: chưa có" in text
        assert "Số điện thoại: chưa có" in text
        assert "Công việc mong muốn: chưa có" in text


# ---------------------------------------------------------------------------
# greeting_gate (reused from memory_service for lead extraction)
# ---------------------------------------------------------------------------

class TestGreetingGate:
    @pytest.mark.parametrize("text", ["ok", "okie", "dạ", "vâng", "cảm ơn", "hi", "hello", "👍", "😊"])
    def test_skips_greetings(self, text):
        assert not greeting_gate(text)

    @pytest.mark.parametrize("text", ["tôi muốn làm", "Dũng", "0357210887", "Hải Phòng", "ca đêm"])
    def test_allows_substantive(self, text):
        assert greeting_gate(text)

    def test_empty_skips(self):
        assert not greeting_gate("")

    def test_none_skips(self):
        assert not greeting_gate(None)

    def test_short_numeric_passes(self):
        """Single/double-digit numeric answers should pass through (e.g. age "5")."""
        assert greeting_gate("25")
        assert greeting_gate("5")

    def test_very_short_alpha_skips(self):
        assert not greeting_gate("ok")
        assert not greeting_gate("da")


# ---------------------------------------------------------------------------
# _lead_collection_question — priority + same-turn guards
# ---------------------------------------------------------------------------

class TestLeadCollectionQuestion:
    """Tests for the probing question selection in runner.py."""

    @pytest.fixture(autouse=True)
    def _import_runner_helpers(self):
        from app.graph.runner import (
            _ASKABLE_FIELDS,
            _FIELD_DETECT_KW,
            _lead_collection_question,
        )
        self._ask = _lead_collection_question
        self._askable = _ASKABLE_FIELDS
        self._kw = _FIELD_DETECT_KW

    def _msg(self, sender, body):
        return SimpleNamespace(sender=sender, body=body, delivery_status="SENT")

    def test_new_lead_asks_name(self):
        q = self._ask(lead=None, current_user_text="xin chào", recent_messages=[])
        assert "tên" in q.lower()

    def test_has_name_no_phone_asks_phone(self):
        lead = {"name": "Dũng"}
        q = self._ask(lead=lead, current_user_text="hello", recent_messages=[])
        assert "điện thoại" in q.lower()

    def test_has_name_phone_asks_desired_job(self):
        lead = {"name": "Dũng", "phone": "0987654321"}
        q = self._ask(lead=lead, current_user_text="hello", recent_messages=[])
        assert "vị trí" in q.lower() or "công việc" in q.lower()

    def test_has_job_asks_region(self):
        lead = {"name": "Dũng", "phone": "0987", "desired_job": "kho"}
        q = self._ask(lead=lead, current_user_text="ok", recent_messages=[])
        assert "tỉnh" in q.lower() or "thành" in q.lower()

    def test_has_region_asks_living_area(self):
        lead = {"name": "Dũng", "phone": "0987", "desired_job": "kho", "region": "Hải Phòng"}
        q = self._ask(lead=lead, current_user_text="ok", recent_messages=[])
        assert "sinh sống" in q.lower()

    def test_has_living_asks_salary(self):
        lead = {"name": "Dũng", "phone": "0987", "desired_job": "kho",
                "region": "Hải Phòng", "living_area": "An Lão"}
        q = self._ask(lead=lead, current_user_text="ok", recent_messages=[])
        assert "lương" in q.lower()

    def test_all_fields_returns_empty(self):
        lead = {"name": "Dũng", "phone": "0987", "desired_job": "kho",
                "region": "HP", "living_area": "An Lão", "expected_salary": "8tr",
                "notes": "xăm kín"}
        q = self._ask(lead=lead, current_user_text="ok", recent_messages=[])
        assert q == ""

    def test_current_text_has_phone_skips_phone_ask(self):
        lead = {"name": "Dũng"}
        q = self._ask(lead=lead, current_user_text="sdt 0987654321", recent_messages=[])
        # Should not ask for phone — user just gave it
        assert "điện thoại" not in q.lower()

    def test_current_text_has_job_keyword_skips_job_ask(self):
        lead = {"name": "Dũng", "phone": "0987"}
        q = self._ask(lead=lead, current_user_text="tôi muốn làm công nhân", recent_messages=[])
        assert "vị trí" not in q.lower() and "công việc" not in q.lower()

    def test_current_text_has_salary_keyword_skips_salary_ask(self):
        lead = {"name": "Dũng", "phone": "0987", "desired_job": "kho",
                "region": "HP", "living_area": "An Lão"}
        q = self._ask(lead=lead, current_user_text="lương 8 triệu là được", recent_messages=[])
        assert "lương" not in q.lower() or q == ""

    def test_current_text_has_region_keyword_skips_region_ask(self):
        lead = {"name": "Dũng", "phone": "0987", "desired_job": "kho"}
        q = self._ask(lead=lead, current_user_text="tôi ở Hải Phòng", recent_messages=[])
        assert "tỉnh" not in q.lower() and "thành" not in q.lower()


# ---------------------------------------------------------------------------
# _ensure_lead_collection_question — append-only (G7 fix)
# ---------------------------------------------------------------------------

class TestEnsureLeadCollectionQuestion:
    @pytest.fixture(autouse=True)
    def _import(self):
        from app.graph.runner import _ensure_lead_collection_question
        self._ensure = _ensure_lead_collection_question

    def test_no_question_returns_reply(self):
        assert self._ensure("hello", "") == "hello"

    def test_empty_reply_returns_question(self):
        assert self._ensure("", "hỏi tên?") == "hỏi tên?"

    def test_question_already_in_reply(self):
        reply = "Chào bạn, bạn cho tôi xin tên nhé?"
        assert self._ensure(reply, "Bạn cho tôi xin tên?") == reply

    def test_appends_when_missing(self):
        result = self._ensure("Chào bạn, tôi có thể giúp gì?", "Bạn cho tôi xin tên?")
        assert result.endswith("Bạn cho tôi xin tên?")
        assert "Chào bạn, tôi có thể giúp gì?" in result

    def test_never_replaces_last_paragraph(self):
        """The old code replaced the model's last paragraph — now it always appends."""
        reply = "Chào bạn!\n\nBạn quan tâm đến vị trí nào?"
        result = self._ensure(reply, "Bạn cho tôi xin tên?")
        # Both paragraphs must survive — the old code would have replaced the last one
        assert "vị trí nào?" in result
        assert "tên" in result
