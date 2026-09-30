"""Tests for grounding enforcement — prevents citing job_ids/entities not in retrieved data.

Pure-function tests: no DB, no LLM. The agent-loop wiring is tested via the
existing graph client integration path (requires langchain).
"""

from __future__ import annotations

from app.graph.grounding import (
    _UngroundedContact,
    extract_asserted_entities,
    extract_cited_job_ids,
    extract_contact_channels,
    extract_surfaced_entities,
    extract_surfaced_job_ids,
    ground_reply,
    validate_contact_grounding,
    validate_entity_grounding,
    validate_grounding,
)

# Stable test UUIDs
JOB_A = "11111111-aaaa-4bbb-8ccc-222222222222"
JOB_B = "33333333-dddd-4eee-9fff-444444444444"
JOB_FAKE = "55555555-6666-4777-8888-999999999999"

# Structured tool payloads (mirrors tools.py rendering).
_ACTIVE_JOB_RESULT = (
    'ACTIVE_JOB_LOOKUP_JSON={"status":"matched","jobs":['
    '{"id":"abc","title":"Công nhân","company":"LG Display","factory":"Hải Phòng",'
    '"project":"LG Display HP","project_slug":"lg-display-hp"}'
    '],"safe_reply":"VFIC hiện có các vị trí ACTIVE sau:"}\n'
    "SURFACED_JOB_IDS=id=abc"
)
_FEATURES_RESULT = (
    "Đặc điểm sản phẩm — dự án 'samsung-bac-ninh':\n"
    "- housing: có KTX [NỔI BẬT]\n"
    "QUY TẮC: chỉ tư vấn dựa trên dữ liệu trên."
)


# --- ID extraction -----------------------------------------------------------


def test_extract_surfaced_ids_from_tagged_form():
    tool_result = f"- Nhân viên kho (id={JOB_A}); lương 10tr"
    assert extract_surfaced_job_ids([tool_result]) == {JOB_A}


def test_extract_surfaced_ids_handles_multiple_results():
    results = [f"id={JOB_A}", f"id={JOB_B}"]
    assert extract_surfaced_job_ids(results) == {JOB_A, JOB_B}


def test_extract_cited_ids_catches_bare_uuid():
    reply = f"Theo tin tuyển dụng {JOB_A}, lương là 10 triệu."
    assert extract_cited_job_ids(reply) == {JOB_A}


def test_extract_cited_ids_catches_tagged_form():
    reply = f"Việc (id={JOB_B}) có KTX."
    assert extract_cited_job_ids(reply) == {JOB_B}


def test_extract_ids_empty_on_no_match():
    assert extract_surfaced_job_ids(["no ids here"]) == set()
    assert extract_cited_job_ids("just text") == set()


# --- contact-channel grounding ----------------------------------------------


_INVENTED_HOTLINE_REPLY = (
    "Dạ em xin lỗi ạ, việc reset mật khẩu tài khoản payroll LG Display nằm ngoài "
    "phạm vi hỗ trợ tuyển dụng của em ạ.\n\n"
    "Chị vui lòng liên hệ trực tiếp bộ phận IT tại nhà máy LG Display qua:\n"
    "- Hotline nội bộ IT: (0251) 543-6789 (máy lẻ 2345)\n"
    "- Email IT: it-helpdesk@lgdisplay.com"
)


def test_extract_contact_channels_normalizes_phones_and_emails():
    channels = extract_contact_channels("Gọi 0357210888 hoặc +84 987 654 321, mail A@B.VN")
    assert channels == {"0357210888", "0987654321", "a@b.vn"}


def test_contact_grounding_flags_the_invented_hotline():
    """The observed LG Display payroll refusal invented both a hotline and an e-mail."""
    unverified = validate_contact_grounding(_INVENTED_HOTLINE_REPLY, "Anh cho em số điện thoại")
    assert unverified == {"02515436789", "it-helpdesk@lgdisplay.com"}


def test_contact_grounding_allows_numbers_from_evidence():
    evidence = "Liên hệ VFIC: 0987 654 321 — hotline@vfic.vn"
    reply = "Anh/chị gọi 0987654321 hoặc gửi mail hotline@vfic.vn nhé ạ."
    assert validate_contact_grounding(reply, evidence) == frozenset()


def test_contact_grounding_allows_the_candidates_own_number():
    assert (
        validate_contact_grounding("Em sẽ liên hệ lại số 0357210888 ạ.", "số của em 0357210888")
        == frozenset()
    )


def test_contact_grounding_ignores_non_phone_numbers():
    """Salary figures and job counts are not contact channels."""
    assert extract_contact_channels("Lương 15.000.000đ, 3 vị trí, id=1234") == frozenset()


def test_ground_reply_flags_an_invented_contact_reply():
    result = ground_reply(
        _INVENTED_HOTLINE_REPLY,
        [],
        allowed_text="Anh cần reset mật khẩu payroll LG Display ạ",
    )
    assert isinstance(result, _UngroundedContact)
    assert "02515436789" in result.channels
    assert "it-helpdesk@lgdisplay.com" in result.channels


def test_ground_reply_keeps_a_contact_answer_sourced_from_a_tool_result():
    tool_results = ["Liên hệ bộ phận tuyển dụng: 0225 123 456"]
    reply = "Anh/chị liên hệ số 0225 123 456 để được hỗ trợ ạ."
    assert ground_reply(reply, tool_results, allowed_text="cho em xin số liên hệ") == reply


def test_ground_reply_contact_guard_is_off_without_prompt_text():
    """Callers that do not pass the prompt keep the previous behaviour."""
    assert ground_reply(_INVENTED_HOTLINE_REPLY, []) == _INVENTED_HOTLINE_REPLY


# --- validate_grounding ------------------------------------------------------


def test_validate_grounding_passes_when_all_cited_ids_were_surfaced():
    reply = f"Việc (id={JOB_A}) phù hợp với bạn."
    result = validate_grounding(reply, {JOB_A})
    assert result.is_grounded
    assert not result.hallucinated_ids
    assert result.sanitized_reply == reply


def test_validate_grounding_flags_hallucinated_id():
    """A cited ID not in the surfaced set is a hallucination."""
    reply = f"Việc (id={JOB_FAKE}) lương 20 triệu."
    result = validate_grounding(reply, {JOB_A})
    assert not result.is_grounded
    assert result.hallucinated_ids == frozenset({JOB_FAKE})
    assert result.reason == "cited_job_id_not_in_retrieved_set"


def test_validate_grounding_strips_hallucinated_id_from_reply():
    reply = f"Gợi ý việc (id={JOB_FAKE}) cho bạn."
    result = validate_grounding(reply, {JOB_A})
    assert JOB_FAKE not in result.sanitized_reply
    assert "[việc không xác định]" in result.sanitized_reply


def test_validate_grounding_no_citation_is_grounded():
    """A reply that cites no job IDs at all is trivially grounded (e.g. small talk)."""
    result = validate_grounding("Chào bạn, tôi có thể giúp gì?", set())
    assert result.is_grounded
    assert not result.hallucinated_ids


def test_validate_grounding_empty_surfaced_flags_all_citations():
    """If no job data was retrieved, any job_id citation is suspect."""
    reply = f"Việc (id={JOB_A}) tốt lắm."
    result = validate_grounding(reply, set())
    assert not result.is_grounded
    assert JOB_A in result.hallucinated_ids


def test_validate_grounding_preserves_grounded_content():
    """When some IDs are real and some fake, only the fake ones are stripped."""
    reply = f"Việc (id={JOB_A}) phù hợp; còn việc (id={JOB_FAKE}) cũng được."
    result = validate_grounding(reply, {JOB_A})
    assert not result.is_grounded
    assert result.hallucinated_ids == frozenset({JOB_FAKE})
    # Real ID preserved
    assert JOB_A in result.sanitized_reply
    # Fake ID stripped
    assert JOB_FAKE not in result.sanitized_reply


# --- entity surfacing --------------------------------------------------------


def test_extract_surfaced_entities_from_active_job_payload():
    """Company/factory/project names are pulled from the ACTIVE_JOB_LOOKUP_JSON row."""
    entities = extract_surfaced_entities([_ACTIVE_JOB_RESULT])
    assert "LG Display" in entities
    assert "Hải Phòng" in entities
    assert "LG Display HP" in entities


def test_extract_surfaced_entities_from_product_features_header():
    """Project slug is pulled from the get_product_features 'dự án ...' header."""
    entities = extract_surfaced_entities([_FEATURES_RESULT])
    assert "samsung-bac-ninh" in entities


def test_extract_surfaced_entities_ignores_free_text_chunks():
    """Only structured payloads are authoritative — plain KB chunks don't count."""
    chunk = "- Ký túc xá 6 người/phòng (Nguồn: tin tuyển dụng Rorze)"
    assert extract_surfaced_entities([chunk]) == set()


def test_extract_surfaced_entities_empty_on_no_payloads():
    assert extract_surfaced_entities([]) == set()
    assert extract_surfaced_entities(["Không tìm thấy thông tin."]) == set()


# A no_match payload now carries ``alternative_jobs`` structurally so the model
# can pivot the candidate AND the entity-grounding layer can verify it only
# names companies that were actually surfaced (replacing the removed regex
# consistency gate that fired a third LLM call). ``jobs`` stays empty so the
# abstention signal the authority layer keys on is unchanged.
_NO_MATCH_WITH_ALTERNATIVES = (
    'ACTIVE_JOB_LOOKUP_JSON={"status":"no_match","jobs":[],"alternative_jobs":['
    '{"id":"alt1","title":"Công nhân","company":"Samsung","factory":"Bắc Ninh",'
    '"project":"Samsung Bắc Ninh","project_slug":"samsung-bac-ninh"}'
    '],"safe_reply":"Hiện chưa có vị trí phù hợp. Hiện đang tuyển Samsung."}\n'
    "SURFACED_JOB_IDS=id=alt1"
)


def test_extract_surfaced_entities_reads_alternative_jobs_on_no_match():
    """No-match alternatives are surfaced as entities, not just safe_reply text.

    This is the structural replacement for the removed regex consistency gate:
    the entity-grounding layer can now verify a no_match reply names only
    companies/factories that were actually returned as alternatives.
    """
    entities = extract_surfaced_entities([_NO_MATCH_WITH_ALTERNATIVES])
    assert "Samsung" in entities
    assert "Bắc Ninh" in entities
    assert "Samsung Bắc Ninh" in entities


def test_validate_grounding_flags_invented_entity_on_no_match_alternative():
    """An invented company on a no_match turn is hedged, not LLM-rewritten.

    Replaces the old negative-authority regex rewrite (which fired a third LLM
    call). The reply is preserved and a hedging footer is appended — same
    sanitize-only pattern used on matched turns.
    """
    surfaced = extract_surfaced_entities([_NO_MATCH_WITH_ALTERNATIVES])
    # LG was never returned as an alternative (only Samsung was).
    reply = "Hiện chưa có vị trí phù hợp. Nhưng LG Display có mức lương 30 triệu."
    result = validate_grounding(reply, set(), surfaced)
    assert not result.is_grounded
    assert "lg display" in result.unsupported_entities
    # Detection-only: the entity is flagged for the trace, the candidate-facing
    # reply is handed back untouched (no hedging footer).
    assert "chưa được xác minh" not in result.sanitized_reply
    assert result.sanitized_reply == reply


def test_validate_grounding_accepts_alternative_entity_on_no_match():
    """Naming a legitimately-surfaced alternative company is grounded."""
    surfaced = extract_surfaced_entities([_NO_MATCH_WITH_ALTERNATIVES])
    reply = "Hiện chưa có vị trí phù hợp. Samsung đang tuyển, bạn muốn xem không?"
    result = validate_grounding(reply, set(), surfaced)
    assert result.is_grounded


# --- asserted entities -------------------------------------------------------


def test_extract_asserted_entities_catches_property_claim():
    """A 'có X' property assertion yields its entity subject."""
    assert extract_asserted_entities("Rorze không có KTX.") == {"rorze"}
    assert extract_asserted_entities("LG Display có hỗ trợ chỗ ở.") == {"lg display"}


def test_extract_asserted_entities_ignores_pronouns_and_discourse():
    """Pronouns, generic nouns, and discourse adverbs are not entities."""
    for reply in (
        "Bạn có muốn xem thêm việc khác không?",
        "Tôi có thể giúp gì cho bạn?",
        "Công ty có đang tuyển không?",
        "Hiện tại chưa có KTX.",
        "Hiện chưa có thông tin đã xác minh.",
        "Vẫn chưa ghi rõ thông tin.",
        "Công ty chúng tôi có hỗ trợ người lao động.",
    ):
        assert extract_asserted_entities(reply) == set(), reply


def test_extract_asserted_entities_strips_wrapping_connectors():
    """Leading/trailing Vietnamese connectors do not pollute the entity."""
    assert extract_asserted_entities("còn Samsung thì có KTX.") == {"samsung"}
    assert extract_asserted_entities("Riêng Rorze không có KTX.") == {"rorze"}


# --- validate_entity_grounding -----------------------------------------------


def test_entity_grounding_flags_unsupported_entity():
    """Asserting a property about an entity the evidence never surfaced is flagged."""
    reply = "Theo dữ liệu, Rorze không có KTX."
    unsupported, sanitized = validate_entity_grounding(reply, {"lg-display"})
    assert unsupported == frozenset({"rorze"})
    # Flagged for the trace, but the reply itself is never annotated.
    assert "chưa được xác minh" not in sanitized
    assert sanitized == reply


def test_entity_grounding_slug_matches_display_name():
    """A surfaced slug ('lg-display') supports a display-name claim ('LG Display')."""
    reply = "LG Display có ký túc xá cho người ở xa."
    unsupported, sanitized = validate_entity_grounding(reply, {"lg-display"})
    assert unsupported == frozenset()
    assert sanitized == reply


def test_entity_grounding_rejects_ambiguous_partial_entity_match():
    """A shared brand/token does not make a different project authoritative."""
    unsupported, _ = validate_entity_grounding(
        "Samsung Bắc Giang có KTX.", {"samsung-bac-ninh", "lg-display"}
    )
    assert unsupported == frozenset({"samsung bac giang"})


def test_entity_grounding_rejects_single_token_abbreviation():
    unsupported, _ = validate_entity_grounding("Samsung có KTX.", {"samsung-bac-ninh"})
    assert unsupported == frozenset({"samsung"})


def test_entity_grounding_abstention_reply_never_flagged():
    """An honest 'chưa có thông tin' reply must not get a hedging footer."""
    for reply in (
        "Hiện chưa có thông tin KTX đã xác minh ở các dự án.",
        "Hiện tại chưa có KTX.",
    ):
        unsupported, sanitized = validate_entity_grounding(reply, {"lg-display"})
        assert unsupported == frozenset(), reply
        assert sanitized == reply


def test_entity_grounding_no_surfaced_entities_is_noop():
    """Without structured entity evidence we cannot distinguish hallucination → skip."""
    reply = "Rorze không có KTX."
    unsupported, sanitized = validate_entity_grounding(reply, set())
    assert unsupported == frozenset()
    assert sanitized == reply


# --- validate_grounding integration (job IDs + entities together) -------------


def test_validate_grounding_flags_unsupported_entity_via_third_arg():
    """validate_grounding runs both the job-ID and entity cross-checks."""
    reply = "Rorze không có KTX."
    result = validate_grounding(reply, set(), surfaced_entities={"lg-display"})
    assert not result.is_grounded
    assert result.reason == "unsupported_entity_claim"
    assert result.unsupported_entities == frozenset({"rorze"})


def test_validate_grounding_passes_when_entity_supported():
    """A supported entity claim stays grounded."""
    reply = "LG Display có ký túc xá."
    result = validate_grounding(reply, set(), surfaced_entities={"lg-display"})
    assert result.is_grounded
    assert not result.unsupported_entities
    assert result.sanitized_reply == reply


def test_validate_grounding_handles_both_job_id_and_entity_hallucination():
    """A reply with both a fake job ID and an unsupported entity is flagged for both."""
    reply = f"Việc (id={JOB_FAKE}) phù hợp; Rorze không có KTX."
    result = validate_grounding(
        reply, {JOB_A}, surfaced_entities={"lg-display"}
    )
    assert not result.is_grounded
    assert result.hallucinated_ids == frozenset({JOB_FAKE})
    assert result.unsupported_entities == frozenset({"rorze"})
    # Reason prefers the job-ID finding (first detected); both are sanitized.
    assert result.reason == "cited_job_id_not_in_retrieved_set"
    # The invented job ID is still stripped; only the entity footer is gone.
    assert JOB_FAKE not in result.sanitized_reply
    assert "chưa được xác minh" not in result.sanitized_reply
