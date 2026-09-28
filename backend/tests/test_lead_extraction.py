"""Pure unit tests for the candidate-info extraction + lead-probing pipeline.

No database, no API keys — only deterministic pure functions and simple mocks.
Matches the project convention: plain pytest, no heavy fixtures.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.candidate_extraction import (
    CandidateExtraction,
    CandidateExtractionService,
    candidate_turn,
    has_explicit_human_review_evidence,
)
from app.services.lead.normalizers import (
    _pick,
    extract_self_reported_name,
    lead_profile_text,
    normalize_integer,
    normalize_lead,
    normalize_lead_score,
    normalize_notes,
    normalize_phone,
    parse_lead_json,
)
from app.services.lead.repository import _UPSQL
from app.services.lead.probing import lead_collection_question
from app.services.memory_service import greeting_gate


def test_human_review_evidence_requires_explicit_non_negated_language():
    assert has_explicit_human_review_evidence(
        "Tôi đang kiểm tra bot",
        "bot_testing",
    )
    assert not has_explicit_human_review_evidence(
        "Tôi không kiểm tra bot",
        "bot_testing",
    )
    assert not has_explicit_human_review_evidence(
        "Tôi không gửi spam",
        "spam",
    )


# ---------------------------------------------------------------------------
# parse_lead_json
# ---------------------------------------------------------------------------
class TestParseLeadJson:
    def test_valid_json_dict(self):
        assert parse_lead_json({"name": "Dũng"}) == {"name": "Dũng"}

    def test_valid_json_string(self):
        assert parse_lead_json('{"name": "Dũng"}') == {"name": "Dũng"}

    def test_json_in_code_block(self):
        assert parse_lead_json('```json\n{"name": "Dũng"}\n```') == {"name": "Dũng"}

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


class TestNormalizeNotes:
    def test_returns_atomic_normalized_unique_lines(self):
        notes = """
        - Không có trình độ
        •  Sẵn sàng   làm bất kỳ công việc gì
        1. Không có trình độ
        2) Hỏi về bảo hiểm tại LG Display
        """

        assert normalize_notes(notes) == (
            "Không có trình độ\nSẵn sàng làm bất kỳ công việc gì\nHỏi về bảo hiểm tại LG Display"
        )

    def test_deduplicates_case_and_trailing_punctuation(self):
        assert normalize_notes("Có xe máy.\ncó xe máy\nCÓ XE MÁY!") == "Có xe máy."

    def test_empty_notes_return_none(self):
        assert normalize_notes("\n - \n\t") is None

    def test_preserves_decimal_leading_facts(self):
        assert normalize_notes("1.5 năm kinh nghiệm\n2.000.000 đồng phụ cấp") == (
            "1.5 năm kinh nghiệm\n2.000.000 đồng phụ cấp"
        )


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
# normalize_lead — notes routing and full output
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

    def test_notes_are_normalized_as_individual_lines(self):
        raw = '{"notes": "- Có xe máy\\n• Ca ngày\\n1. Có xe máy"}'
        result = normalize_lead(raw, "zalo_1")
        assert result["notes"] == "Có xe máy\nCa ngày"

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
# extract_self_reported_name — deterministic fallback for "tôi tên ..."
# ---------------------------------------------------------------------------
class TestExtractSelfReportedName:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("tôi tên Mai", "Mai"),
            ("em tên là Nguyễn Thị Mai, sdt 0987654321", "Nguyễn Thị Mai"),
            ("Tên mình là Lan", "Lan"),
        ],
    )
    def test_extracts_explicit_name_phrases(self, text, expected):
        assert extract_self_reported_name(text) == expected

    @pytest.mark.parametrize("text", ["tôi là công nhân", "muốn làm hè thôi ạ", "Mai"])
    def test_does_not_guess_without_name_keyword(self, text):
        assert extract_self_reported_name(text) is None

    @pytest.mark.parametrize(
        "prev",
        [
            "Bạn tên gì vậy?",
            "Cho mình xin tên để tiện hỗ trợ nhé 😊",
            "Mình xưng hô với nhau nha!",
            "ban ten la gi",
        ],
    )
    def test_captures_bare_name_when_bot_just_asked(self, prev):
        assert extract_self_reported_name("Dũng", prev_bot_message=prev) == "Dũng"
        assert (
            extract_self_reported_name("Nguyễn Thị Mai", prev_bot_message=prev)
            == "Nguyễn Thị Mai"
        )

    def test_strips_trailing_particles_off_bare_name(self):
        assert (
            extract_self_reported_name("Dũng ạ", prev_bot_message="Bạn tên gì?")
            == "Dũng"
        )
        assert (
            extract_self_reported_name("Mai nhé", prev_bot_message="Bạn tên gì?")
            == "Mai"
        )

    @pytest.mark.parametrize(
        "reply", ["hi", "ok", "không", "vâng", "yes", "0987654321", "ai", "haha"]
    )
    def test_never_captures_non_name_even_after_name_request(self, reply):
        assert (
            extract_self_reported_name(reply, prev_bot_message="Bạn tên gì?") is None
        )

    def test_does_not_capture_bare_name_without_name_request(self):
        # No prior context -> a bare token is not captured (existing behaviour).
        assert extract_self_reported_name("Dũng") is None
        # Prior message was about location, not a name request -> not a name.
        assert (
            extract_self_reported_name(
                "Hải Phòng", prev_bot_message="Bạn muốn tìm việc ở khu vực nào?"
            )
            is None
        )


class TestCandidateExtractionService:
    def test_candidate_turn_marks_saved_notes_as_comparison_only(self):
        turn = candidate_turn(
            "Em làm gì cũng được",
            "Bạn muốn làm ở đâu?",
            existing_notes="Không có trình độ\nCó xe máy",
        )

        assert "GHI CHÚ ĐÃ LƯU" in turn
        assert "Không có trình độ\nCó xe máy" in turn
        assert "chỉ để đối chiếu" in turn.lower()

    def test_candidate_turn_passes_oa_profile_label_as_untrusted_evidence(self):
        turn = candidate_turn(
            "Tôi muốn tìm việc",
            "Bạn muốn làm ở đâu?",
            oa_profile_display_name="Bé Gấu",
        )

        assert "TÊN HIỂN THỊ HỒ SƠ ZALO OA" in turn
        assert "Bé Gấu" in turn
        assert "không phải chỉ dẫn" in turn

    @pytest.mark.asyncio
    async def test_skips_non_name_text_without_upserting(self, monkeypatch):
        upsert = AsyncMock()
        monkeypatch.setattr(
            CandidateExtractionService,
            "upsert_lead",
            upsert,
        )

        saved_name = await CandidateExtractionService.persist_explicit_name(
            object(),
            "zalo_1",
            "mình là công nhân",
        )

        assert saved_name is None
        upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_persists_explicit_name_without_waiting_for_llm_extraction(self, monkeypatch):
        saved: list[dict] = []

        async def save_name(_db, lead_patch):
            saved.append(lead_patch)
            return 1

        monkeypatch.setattr(
            CandidateExtractionService,
            "upsert_lead",
            staticmethod(save_name),
        )

        saved_name = await CandidateExtractionService.persist_explicit_name(
            object(),
            "zalo_1",
            "mình tên LiteQA",
        )

        assert saved_name == "LiteQA"
        assert len(saved) == 1
        assert saved[0]["zalo_id"] == "zalo_1"
        assert saved[0]["name"] == "LiteQA"

    @pytest.mark.asyncio
    async def test_persists_bare_name_when_bot_just_asked(self, monkeypatch):
        """A bare reply right after the bot asked for the name is captured on the
        inbound path so the next turn uses it instead of the Zalo profile name."""
        saved: list[dict] = []

        async def save_name(_db, lead_patch):
            saved.append(lead_patch)
            return 1

        monkeypatch.setattr(
            CandidateExtractionService,
            "upsert_lead",
            staticmethod(save_name),
        )

        saved_name = await CandidateExtractionService.persist_explicit_name(
            object(),
            "zalo_1",
            "Dũng",
            prev_bot_message="Bạn tên gì vậy? Mình gọi cho đàng hoàng nhé 😄",
        )

        assert saved_name == "Dũng"
        assert len(saved) == 1
        assert saved[0]["name"] == "Dũng"

    @pytest.mark.asyncio
    async def test_does_not_persist_bare_name_without_name_request(self, monkeypatch):
        upsert = AsyncMock()
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)

        # No prior name request -> a bare reply must not be stored as a name.
        saved_name = await CandidateExtractionService.persist_explicit_name(
            object(),
            "zalo_1",
            "Dũng",
            prev_bot_message="Bạn muốn tìm việc ở khu vực nào?",
        )

        assert saved_name is None
        upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_extracts_lead_patch_and_memory_facts_from_one_llm_call(self):
        calls = 0

        async def extractor(_system: str, _turn: str) -> str:
            nonlocal calls
            calls += 1
            return """
            {
              "lead_patch": {
                "name": null,
                "phone": null,
                "birth_year": null,
                "age": null,
                "living_area": null,
                "address": null,
                "gender": null,
                "region": null,
                "desired_job": "lao động thời vụ",
                "years_experience": null,
                "expected_salary": null,
                "lead_score": "warm",
                "notes": null
              },
              "memory_facts": ["Người dùng tên là Mai", "Muốn làm thời vụ"],
              "contact_intent": "candidate",
              "intent_confidence": 0.99
            }
            """

        result = await CandidateExtractionService.extract(
            extractor,
            "tôi tên Mai",
            "Rất vui được biết bạn, Mai!",
            "zalo_1",
        )

        assert calls == 1
        assert result.lead_patch["name"] == "Mai"
        assert result.lead_patch["desired_job"] == "lao động thời vụ"
        assert result.lead_patch["lead_score"] == "warm"
        assert result.memory_facts == ["Người dùng tên là Mai", "Muốn làm thời vụ"]
        assert result.contact_intent == "candidate"
        assert result.intent_confidence == 0.99
        assert result.requires_human_review is False

    @pytest.mark.asyncio
    async def test_extracts_high_confidence_non_candidate_intent_separately_from_notes(self):
        async def extractor(_system: str, _turn: str) -> str:
            return """
            {
              "lead_patch": null,
              "memory_facts": [],
              "contact_intent": "non_candidate",
              "intent_confidence": 0.99
            }
            """

        result = await CandidateExtractionService.extract(
            extractor,
            "Tôi không phải ứng viên",
            "Tôi có thể hỗ trợ bạn tìm việc.",
            "zalo_1",
        )

        assert result.lead_patch is None
        assert result.memory_facts == []
        assert result.contact_intent == "non_candidate"
        assert result.requires_human_review is True

    @pytest.mark.asyncio
    async def test_invalid_intent_or_confidence_fails_closed_to_uncertain(self):
        async def extractor(_system: str, _turn: str) -> str:
            return (
                '{"lead_patch":null,"memory_facts":[],"contact_intent":"block_user",'
                '"intent_confidence":5}'
            )

        result = await CandidateExtractionService.extract(
            extractor,
            "Nội dung bất kỳ",
            "Phản hồi",
            "zalo_1",
        )

        assert result.contact_intent == "uncertain"
        assert result.intent_confidence == 0.0
        assert result.requires_human_review is False

    @pytest.mark.asyncio
    async def test_negative_intent_with_candidate_payload_cannot_escalate_or_persist(self):
        async def extractor(_system: str, _turn: str) -> str:
            return (
                '{"lead_patch":{"phone":"0912345678","desired_job":"kho"},'
                '"memory_facts":["Muốn ứng tuyển việc kho"],'
                '"contact_intent":"bot_testing","intent_confidence":0.99}'
            )

        result = await CandidateExtractionService.extract(
            extractor,
            "Tôi muốn ứng tuyển kho, số điện thoại 0912345678",
            "Tôi sẽ hỗ trợ bạn.",
            "zalo_1",
        )

        assert result.contact_intent == "uncertain"
        assert result.intent_confidence == 0.0
        assert result.lead_patch is None
        assert result.memory_facts == []
        assert result.requires_human_review is False

    @pytest.mark.asyncio
    async def test_low_confidence_negative_intent_never_pollutes_notes_or_memory(self):
        async def extractor(_system: str, _turn: str) -> str:
            return (
                '{"lead_patch":{"notes":"Người dùng gửi nội dung kiểm tra bảo mật"},'
                '"memory_facts":["Người dùng không phải ứng viên"],'
                '"contact_intent":"bot_testing","intent_confidence":0.94}'
            )

        result = await CandidateExtractionService.extract(
            extractor,
            "Tôi đang kiểm tra bảo mật",
            "Phản hồi",
            "zalo_1",
        )

        assert result.contact_intent == "uncertain"
        assert result.intent_confidence == 0.0
        assert result.lead_patch is None
        assert result.memory_facts == []
        assert result.requires_human_review is False

    @pytest.mark.asyncio
    async def test_extract_includes_existing_notes_for_llm_deduplication(self):
        captured_turn = ""

        async def extractor(_system: str, turn: str) -> str:
            nonlocal captured_turn
            captured_turn = turn
            return '{"lead_patch":{"notes":"Hỏi về bảo hiểm"},"memory_facts":[]}'

        result = await CandidateExtractionService.extract(
            extractor,
            "Bảo hiểm thế nào?",
            "Bạn được tham gia bảo hiểm.",
            "zalo_1",
            existing_notes="Không có trình độ",
        )

        assert "GHI CHÚ ĐÃ LƯU" in captured_turn
        assert "Không có trình độ" in captured_turn
        assert result.lead_patch["notes"] == "Hỏi về bảo hiểm"

    @pytest.mark.asyncio
    async def test_persist_supplies_saved_notes_to_extract(self, monkeypatch):
        db = object()
        llm_extractor = AsyncMock()
        extract = AsyncMock(return_value=CandidateExtraction(lead_patch=None, memory_facts=[]))
        upsert = AsyncMock(return_value=None)

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return {"notes": "Không có trình độ\nCó xe máy"}

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return None

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", extract)
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)

        await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            llm_extractor,
            "zalo_1",
            "Bảo hiểm thế nào?",
            "Bạn được tham gia bảo hiểm.",
        )

        extract.assert_awaited_once_with(
            llm_extractor,
            "Bảo hiểm thế nào?",
            "Bạn được tham gia bảo hiểm.",
            "zalo_1",
            existing_notes="Không có trình độ\nCó xe máy",
            oa_profile_display_name=None,
        )
        upsert.assert_awaited_once_with(db, None, contact_id=None)

    @pytest.mark.asyncio
    async def test_persist_supplies_oa_profile_name_to_llm_judgment(self, monkeypatch):
        extract = AsyncMock(
            return_value=CandidateExtraction(lead_patch=None, memory_facts=[])
        )

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return {"notes": None}

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return SimpleNamespace(
                    mode=ConversationMode.BOT,
                    status=ConversationStatus.OPEN,
                    version=1,
                    contact=SimpleNamespace(display_name="Bé Gấu"),
                    zalo_chat_id="zalo_1",
                    contact_id="contact-1",
                )

        from app.models.conversation import ConversationMode, ConversationStatus

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", extract)
        monkeypatch.setattr(
            CandidateExtractionService,
            "upsert_lead",
            AsyncMock(return_value=None),
        )

        await CandidateExtractionService.persist(
            object(),
            AsyncMock(),
            AsyncMock(),
            "oa:user-1",
            "Tôi muốn tìm việc",
            "Bạn muốn làm ở đâu?",
        )

        assert extract.await_args.kwargs["oa_profile_display_name"] == "Bé Gấu"

    @pytest.mark.asyncio
    async def test_confirmed_name_prevents_oa_label_from_replacing_it(self, monkeypatch):
        extract = AsyncMock(
            return_value=CandidateExtraction(lead_patch=None, memory_facts=[])
        )

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return {"name": "Nguyễn Văn An", "notes": None}

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return SimpleNamespace(
                    mode=ConversationMode.BOT,
                    status=ConversationStatus.OPEN,
                    version=1,
                    contact=SimpleNamespace(display_name="Bé Gấu"),
                    zalo_chat_id="zalo_1",
                    contact_id="contact-1",
                )

        from app.models.conversation import ConversationMode, ConversationStatus

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", extract)
        monkeypatch.setattr(
            CandidateExtractionService,
            "upsert_lead",
            AsyncMock(return_value=None),
        )

        await CandidateExtractionService.persist(
            object(),
            AsyncMock(),
            AsyncMock(),
            "oa:user-1",
            "Tôi muốn tìm việc",
            "Bạn muốn làm ở đâu?",
        )

        assert extract.await_args.kwargs["oa_profile_display_name"] is None

    @pytest.mark.asyncio
    async def test_confirmed_name_survives_later_hallucinated_name(self, monkeypatch):
        db = object()
        extracted = CandidateExtraction(
            lead_patch={
                "zalo_id": "zalo_1",
                "name": "CTY ở đâu vậy",
                "desired_job": "CNC",
            },
            memory_facts=[],
        )
        upsert = AsyncMock(return_value=None)

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return {"name": "Hùng", "notes": None}

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return None

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        monkeypatch.setattr(
            CandidateExtractionService,
            "extract",
            AsyncMock(return_value=extracted),
        )
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)

        result = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "zalo_1",
            "CTY ở đâu vậy",
            "Công ty ở Hải Phòng.",
        )

        assert result.lead_patch is not None
        assert result.lead_patch["name"] is None
        assert result.lead_patch["desired_job"] == "CNC"
        upsert.assert_awaited_once_with(db, result.lead_patch, contact_id=None)

    @pytest.mark.asyncio
    async def test_oa_profile_context_cannot_turn_question_into_canonical_name(
        self, monkeypatch
    ):
        from app.models.conversation import ConversationMode, ConversationStatus

        db = object()
        extracted = CandidateExtraction(
            lead_patch={"zalo_id": "oa:user-1", "name": "CTY ở đâu vậy"},
            memory_facts=[],
        )
        upsert = AsyncMock(return_value=None)

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return {"name": None, "notes": None}

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return type(
                    "_Conversation",
                    (),
                    {
                        "mode": ConversationMode.BOT,
                        "status": ConversationStatus.OPEN,
                        "version": 3,
                        "zalo_chat_id": "oa:user-1",
                        "contact_id": "contact-1",
                        "contact": type(
                            "_Contact",
                            (),
                            {"display_name": "Nguyễn Hùng"},
                        )(),
                    },
                )()

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        monkeypatch.setattr(
            CandidateExtractionService,
            "extract",
            AsyncMock(return_value=extracted),
        )
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)

        result = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "oa:user-1",
            "CTY ở đâu vậy",
            "Công ty ở Hải Phòng.",
            expected_conversation_version=3,
        )

        assert result.lead_patch is not None
        assert result.lead_patch["name"] is None
        upsert.assert_awaited_once_with(db, result.lead_patch, contact_id=None)

    @pytest.mark.asyncio
    async def test_explicit_name_correction_replaces_confirmed_name(self, monkeypatch):
        db = object()
        extracted = CandidateExtraction(
            lead_patch={
                "zalo_id": "zalo_1",
                "name": "wrong model value",
                "desired_job": "CNC",
            },
            memory_facts=[],
        )
        upsert = AsyncMock(return_value=None)

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return {"name": "Hùng", "notes": None}

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return None

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        monkeypatch.setattr(
            CandidateExtractionService,
            "extract",
            AsyncMock(return_value=extracted),
        )
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)

        result = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "zalo_1",
            "Em là Nguyễn Văn Hưng, em muốn tìm việc",
            "Cảm ơn bạn Hưng.",
        )

        assert result.lead_patch is not None
        assert result.lead_patch["name"] == "Nguyễn Văn Hưng"
        assert result.lead_patch["desired_job"] == "CNC"
        upsert.assert_awaited_once_with(db, result.lead_patch, contact_id=None)

    @pytest.mark.asyncio
    async def test_persist_skips_llm_when_conversation_is_already_human(self, monkeypatch):
        from app.models.conversation import ConversationMode

        db = object()
        extractor = AsyncMock()
        lead_repository = MagicMock()

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return SimpleNamespace(
                    mode=ConversationMode.HUMAN,
                    status="OPEN",
                    version=1,
                )

        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            lead_repository,
        )

        result = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            extractor,
            "zalo_1",
            "Tôi tiếp tục gửi tin sau khi đã chuyển nhân viên",
            "Phản hồi cũ",
        )

        assert result == CandidateExtraction(lead_patch=None, memory_facts=[])
        extractor.assert_not_awaited()
        lead_repository.assert_not_called()

    @pytest.mark.asyncio
    async def test_persist_skips_llm_for_closed_conversation(self, monkeypatch):
        db = object()
        extractor = AsyncMock()

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return SimpleNamespace(mode="BOT", status="CLOSED", version=1)

        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )

        result = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            extractor,
            "zalo_1",
            "Tôi đang kiểm tra bot",
            "Phản hồi cũ",
            expected_conversation_version=1,
        )

        assert result == CandidateExtraction(lead_patch=None, memory_facts=[])
        extractor.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_persist_runs_when_only_the_turn_outcome_bumped_the_version(
        self, monkeypatch
    ):
        """The shape every live job has: the turn's own outcome bumped the version.

        The persist job is enqueued after ``record_bot_outcome``, which bumps
        ``Conversation.version`` as it completes the turn the job describes, so
        the captured turn-start version is already stale. Skipping on that
        mismatch made every live extraction a silent no-op: the model ran, the
        job reported success, and nothing was written.
        """
        db = object()
        extract = AsyncMock(
            return_value=CandidateExtraction(
                lead_patch={"phone": "0359151980"},
                memory_facts=[],
            )
        )
        upsert = AsyncMock()
        conversation = SimpleNamespace(
            id="conversation-1",
            mode="BOT",
            status="OPEN",
            version=2,
            zalo_chat_id="zalo_1",
            contact_id="contact-1",
        )

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return None

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return conversation

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", extract)
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )

        result = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "zalo_1",
            "0359151980",
            "Dạ em ghi nhận số điện thoại ạ",
            expected_conversation_version=1,
        )

        assert result.lead_patch == {"phone": "0359151980"}
        upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_escalates_high_confidence_intent_without_lead_or_memory_write(
        self, monkeypatch
    ):
        db = object()
        result = CandidateExtraction(
            lead_patch=None,
            memory_facts=[],
            contact_intent="bot_testing",
            intent_confidence=0.99,
        )
        extract = AsyncMock(return_value=result)
        upsert = AsyncMock()
        conversation = SimpleNamespace(
            id="conversation-1",
            mode="BOT",
            status="OPEN",
            version=1,
            zalo_chat_id="zalo_1",
            contact_id="contact-1",
        )
        escalate = AsyncMock(return_value=True)

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return None

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return conversation

            async def escalate_extracted_intent(
                self,
                selected_conversation,
                *,
                reason: str,
                confidence: float,
                expected_version: int,
            ) -> bool:
                return await escalate(
                    selected_conversation,
                    reason=reason,
                    confidence=confidence,
                    expected_version=expected_version,
                )

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", extract)
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )
        memory_save = AsyncMock()
        monkeypatch.setattr("app.services.candidate_extraction.MemoryService.save", memory_save)

        persisted = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "zalo_1",
            "Tôi đang kiểm tra bot",
            "Bot đã trả lời tin nhắn đầu tiên.",
            expected_conversation_version=1,
        )

        assert persisted is result
        escalate.assert_awaited_once_with(
            conversation,
            reason="bot_testing",
            confidence=0.99,
            expected_version=1,
        )
        upsert.assert_not_awaited()
        memory_save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_persist_does_not_escalate_recruitment_question_from_model_label(
        self, monkeypatch
    ):
        db = object()
        model_result = CandidateExtraction(
            lead_patch=None,
            memory_facts=[],
            contact_intent="non_candidate",
            intent_confidence=0.99,
        )
        extract = AsyncMock(return_value=model_result)
        conversation = SimpleNamespace(
            id="conversation-1",
            mode="BOT",
            status="OPEN",
            version=1,
            zalo_chat_id="zalo_1",
            contact_id="contact-1",
        )
        escalate = AsyncMock(return_value=True)

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_zalo_id(self, _chat_id: str):
                return None

        class FakeConversationService:
            def __init__(self, _db) -> None:
                pass

            async def get_by_zalo(self, _chat_id: str):
                return conversation

            async def escalate_extracted_intent(self, *args, **kwargs) -> bool:
                return await escalate(*args, **kwargs)

        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository",
            FakeLeadRepository,
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", extract)
        monkeypatch.setattr(
            "app.services.conversation.ConversationService",
            FakeConversationService,
        )

        persisted = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "zalo_1",
            (
                "mình nhà ở quoán toan _hp gần lG tràng duệ."
                "bên lG tràng duệ mình đang tuyển ạ"
            ),
            "Hiện VFIC chưa tuyển vị trí này.",
            expected_conversation_version=1,
        )

        assert persisted.contact_intent == "uncertain"
        assert persisted.intent_confidence == 0.0
        escalate.assert_not_awaited()


def test_lead_upsert_deduplicates_individual_note_lines_atomically():
    sql = _UPSQL.text.lower()

    assert "regexp_split_to_table" in sql
    assert "not exists" in sql
    assert "regexp_replace" in sql


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

    def test_oa_personalization_uses_known_name_without_reasking(self):
        lead = {"name": "Nguyễn Văn An"}

        text = lead_profile_text(
            lead,
            oa_profile_display_name="Bé Gấu",
            personalize=True,
        )

        assert "Họ tên: Nguyễn Văn An" in text
        assert "không hỏi lại tên" in text
        assert "gọi tên tự nhiên" in text
        assert "không lặp tên máy móc" in text

    def test_oa_profile_label_is_visible_but_left_for_agent_judgment(self):
        text = lead_profile_text(
            {"name": None},
            oa_profile_display_name="Bé Gấu",
            personalize=True,
        )

        assert "Bé Gấu" in text
        assert "chưa được ứng viên xác nhận" in text
        assert "Tự đánh giá bằng ngữ cảnh" in text

    def test_clear_oa_profile_name_suppresses_reask_without_confirming_identity(self):
        text = lead_profile_text(
            {"name": None},
            oa_profile_display_name="Nguyễn Hùng",
            use_oa_profile_name=True,
            personalize=True,
        )

        assert '"Nguyễn Hùng"' in text
        assert "chưa được ứng viên xác nhận" in text
        assert "không hỏi lại tên" in text
        assert "chưa được ghi vào hồ sơ" in text
        assert "Đã biết tên ứng viên" not in text

    @pytest.mark.parametrize(
        ("display_name", "expected"),
        [
            ("Nguyễn Hùng", "Nguyễn Hùng"),
            ("Trần Văn Nam", "Trần Văn Nam"),
            # Western-order display labels: family name last must also pass.
            ("Duc Huy Nguyen", "Duc Huy Nguyen"),
            ("Nguyen Duc Huy", "Nguyen Duc Huy"),
            ("Thu Ha Nguyen", "Thu Ha Nguyen"),
            ("CTY ở đâu", None),
            ("Bé Gấu", None),
            ("Nguyễn Hùng?", None),
            ("Dũng", None),
            ("Công Ty TNHH ABC", None),
        ],
    )
    def test_high_confidence_profile_name(self, display_name, expected):
        from app.services.lead import high_confidence_profile_name

        assert high_confidence_profile_name(display_name) == expected

    def test_all_fields_populated(self):
        lead = {
            "name": "Lan",
            "phone": "0912",
            "desired_job": "kho",
            "expected_salary": "8 triệu",
            "region": "Hải Phòng",
            "living_area": "An Lão",
            "notes": "xăm kín người",
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
    @pytest.mark.parametrize(
        "text", ["ok", "okie", "dạ", "vâng", "cảm ơn", "hi", "hello", "👍", "😊"]
    )
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
# lead_collection_question — priority + same-turn guards
# ---------------------------------------------------------------------------
class TestLeadCollectionQuestion:
    """Tests for the probing question selection."""

    _ask = staticmethod(lead_collection_question)

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
        lead = {
            "name": "Dũng",
            "phone": "0987",
            "desired_job": "kho",
            "region": "Hải Phòng",
            "living_area": "An Lão",
        }
        q = self._ask(lead=lead, current_user_text="ok", recent_messages=[])
        assert "lương" in q.lower()

    def test_all_fields_returns_empty(self):
        lead = {
            "name": "Dũng",
            "phone": "0987",
            "desired_job": "kho",
            "region": "HP",
            "living_area": "An Lão",
            "expected_salary": "8tr",
            "notes": "xăm kín",
        }
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
        lead = {
            "name": "Dũng",
            "phone": "0987",
            "desired_job": "kho",
            "region": "HP",
            "living_area": "An Lão",
        }
        q = self._ask(lead=lead, current_user_text="lương 8 triệu là được", recent_messages=[])
        assert "lương" not in q.lower() or q == ""

    def test_current_text_has_region_keyword_skips_region_ask(self):
        lead = {"name": "Dũng", "phone": "0987", "desired_job": "kho"}
        q = self._ask(lead=lead, current_user_text="tôi ở Hải Phòng", recent_messages=[])
        assert "tỉnh" not in q.lower() and "thành" not in q.lower()


# ---------------------------------------------------------------------------
# Messenger turns are contact-keyed (Alembic 0047): the conversation carries no
# zalo_chat_id, so the lead must be written and read by contact_id. Keying it
# on the PSID is what raised leads_zalo_id_fkey and lost every Messenger lead.
# ---------------------------------------------------------------------------
class TestContactKeyedPersist:
    @staticmethod
    def _conversation(**overrides):
        from app.models.conversation import ConversationMode, ConversationStatus

        fields = {
            "mode": ConversationMode.BOT,
            "status": ConversationStatus.OPEN,
            "version": 3,
            "zalo_chat_id": None,
            "contact_id": "contact-1",
        }
        return SimpleNamespace(**{**fields, **overrides})

    @pytest.mark.asyncio
    async def test_messenger_turn_writes_the_lead_by_contact(self, monkeypatch):
        db = AsyncMock()
        db.get.return_value = self._conversation()
        lookups: list[str] = []

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_contact_id(self, contact_id: str):
                lookups.append(f"contact:{contact_id}")
                return {"notes": "ở Nam Am, Vĩnh Bảo"}

            async def by_zalo_id(self, _chat_id: str):
                lookups.append("zalo")
                return None

        patch_obj = CandidateExtraction(lead_patch={"phone": "0566866899"}, memory_facts=[])
        upsert = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository", FakeLeadRepository
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", AsyncMock(return_value=patch_obj))
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)

        await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "28225543490450146",
            "số điện thoại của tôi là 0566866899",
            "Cảm ơn bạn",
            contact_id="contact-1",
            conversation_id="c71b264b-82be-4111-9b84-cf2b84dd395e",
        )

        assert lookups == ["contact:contact-1"]
        upsert.assert_awaited_once_with(db, patch_obj.lead_patch, contact_id="contact-1")

    @pytest.mark.asyncio
    async def test_zalo_turn_with_a_contact_keeps_the_zalo_keyed_write(self, monkeypatch):
        db = AsyncMock()
        db.get.return_value = self._conversation(zalo_chat_id="oa:user-1", contact=None)
        lookups: list[str] = []

        class FakeLeadRepository:
            def __init__(self, _db) -> None:
                pass

            async def by_contact_id(self, _contact_id: str):
                lookups.append("contact")
                return None

            async def by_zalo_id(self, chat_id: str):
                lookups.append(f"zalo:{chat_id}")
                return {"notes": None}

        patch_obj = CandidateExtraction(lead_patch={"phone": "0357210887"}, memory_facts=[])
        upsert = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository", FakeLeadRepository
        )
        monkeypatch.setattr(CandidateExtractionService, "extract", AsyncMock(return_value=patch_obj))
        monkeypatch.setattr(CandidateExtractionService, "upsert_lead", upsert)

        await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            AsyncMock(),
            "oa:user-1",
            "số điện thoại của tôi là 0357210887",
            "Cảm ơn bạn",
            contact_id="contact-1",
            conversation_id="3f6b1c22-0f1a-4f1b-9a2f-0a1b2c3d4e5f",
        )

        assert lookups == ["zalo:oa:user-1"]
        upsert.assert_awaited_once_with(db, patch_obj.lead_patch, contact_id=None)

    @pytest.mark.asyncio
    async def test_messenger_turn_respects_the_closed_conversation_guard(self, monkeypatch):
        """A Messenger conversation is now resolvable, so the guard can fire."""
        from app.models.conversation import ConversationStatus

        db = AsyncMock()
        db.get.return_value = self._conversation(status=ConversationStatus.CLOSED)
        extractor = AsyncMock()
        lead_repository = MagicMock()
        monkeypatch.setattr(
            "app.services.candidate_extraction.LeadRepository", lead_repository
        )

        result = await CandidateExtractionService.persist(
            db,
            AsyncMock(),
            extractor,
            "28225543490450146",
            "số điện thoại của tôi là 0566866899",
            "Phản hồi cũ",
            contact_id="contact-1",
            conversation_id="c71b264b-82be-4111-9b84-cf2b84dd395e",
        )

        assert result == CandidateExtraction(lead_patch=None, memory_facts=[])
        extractor.assert_not_awaited()
        lead_repository.assert_not_called()
