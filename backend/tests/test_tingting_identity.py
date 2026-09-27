"""Identity verification decided by code, not by the model's eye.

Production looped on exactly these cases: an unaccented name rejected as a
mismatch, the phone number re-entered as the CCCD, and a record whose CCCD field
cannot be told apart from its mobile. Every one of them is a pure function of the
record and the submitted values, so each is pinned here.
"""

from __future__ import annotations

import pytest

from app.graph.tools.tingting_identity import (
    evaluate_identity,
    normalize_name,
    normalize_phone,
    render_verdict,
    verify_tingting_identity,
)

_RECORD = {
    "found": True,
    "employee_name": "Nguyễn Việt Dũng",
    "cccd": "11112222",
    "mobile": "0357210887",
}


def test_no_verdict_shape_ever_renders_a_record_value() -> None:
    """Every shape of the block is checked, because the leak is one branch deep.

    ``render_verdict`` output is what the model reads before it speaks; a value
    from the record anywhere in it (or in the verdict dict a future caller might
    format) is an answer key handed to the party being verified.
    """
    submitted = (
        {"full_name": "Trần Văn A", "cccd": "99998888", "phone": "0000000000"},
        {"full_name": "Nguyễn Việt Dũng", "cccd": "", "phone": "0357210887"},
        {"full_name": "", "cccd": "", "phone": ""},
        {"full_name": "Nguyen Viet Dung", "cccd": "0357210887", "phone": "0357210887"},
        {"full_name": "Nguyễn Việt Dũng", "cccd": "11112222", "phone": "0357210887"},
    )
    records = (_RECORD, {"found": False}, {"found": True}, {}, None)
    secrets = ("Nguyễn Việt Dũng", "Nguyen Viet Dung", "11112222", "0357210887")
    for record in records:
        for case in submitted:
            verdict = evaluate_identity(record, **case)
            haystacks = [render_verdict(verdict), repr(verdict)]
            for secret in secrets:
                assert all(secret not in text for text in haystacks), (record, case, secret)


def test_name_normalisation_folds_diacritics_case_and_spacing() -> None:
    assert normalize_name("Nguyễn Việt Dũng") == "nguyen viet dung"
    assert normalize_name("  nguyen   VIET dung ") == "nguyen viet dung"
    assert normalize_name("Đặng Đình Đức") == "dang dinh duc"
    assert normalize_phone("+84 357 210 887") == "0357210887"
    assert normalize_phone("0357 210 887") == "0357210887"


def test_an_unaccented_name_matches_the_accented_record() -> None:
    verdict = evaluate_identity(
        _RECORD, full_name="Nguyen Viet Dung", cccd="11112222", phone="0357210887"
    )
    assert verdict["verified"] is True
    assert verdict["missing"] == []


def test_swapped_name_order_still_names_the_same_person() -> None:
    verdict = evaluate_identity(_RECORD, full_name="Dung Viet Nguyen", cccd="11112222", phone="0357210887")
    assert verdict["name_match"] is True
    assert verdict["verified"] is True


def test_a_record_without_a_cccd_does_not_require_one() -> None:
    verdict = evaluate_identity(
        {**_RECORD, "cccd": ""}, full_name="Nguyễn Việt Dũng", phone="0357210887"
    )
    assert verdict["cccd_on_record"] is False
    assert verdict["cccd_required"] is False
    assert verdict["verified"] is True


def test_a_record_whose_cccd_equals_its_mobile_does_not_deadlock() -> None:
    """The reported case: the CCCD field holds the phone, so nothing else can match it."""
    verdict = evaluate_identity(
        {**_RECORD, "cccd": "0357210887"},
        full_name="Nguyễn Việt Dũng",
        cccd="0357210887",
        phone="0357210887",
    )
    assert verdict["cccd_required"] is False
    assert verdict["verified"] is True


def test_the_phone_typed_in_the_cccd_slot_is_named_as_the_phone() -> None:
    verdict = evaluate_identity(
        _RECORD, full_name="Nguyễn Việt Dũng", cccd="0357210887", phone="0357210887"
    )
    assert verdict["verified"] is False
    assert verdict["missing"] == ["cccd"]
    assert verdict["submitted_cccd_is_phone"] is True
    rendered = render_verdict(verdict)
    assert "SỐ ĐIỆN THOẠI" in rendered
    assert "11112222" not in rendered  # the record's CCCD is never echoed


def test_a_wrong_name_asks_only_for_the_name_without_leaking_it() -> None:
    """The employee is the one being verified: the record is an answer key.

    Any value from the record in the model's context could be read back to
    whoever holds the phone number, and a wrong-name turn is exactly where a
    helpful model would quote it.
    """
    verdict = evaluate_identity(
        _RECORD, full_name="Trần Văn A", cccd="11112222", phone="0357210887"
    )
    assert verdict["missing"] == ["full_name"]
    rendered = render_verdict(verdict)
    assert "Nguyễn Việt Dũng" not in rendered
    assert "registered_name" not in verdict
    assert "cần hỏi lại: họ tên đầy đủ" in rendered


def test_a_missing_submission_reports_the_fields_owed() -> None:
    verdict = evaluate_identity(_RECORD, phone="0357210887")
    assert verdict["missing"] == ["full_name", "cccd"]
    assert verdict["verified"] is False


def test_an_unknown_phone_reports_not_found() -> None:
    verdict = evaluate_identity({"found": False}, phone="0987654321")
    assert verdict["found"] is False
    assert verdict["verified"] is False
    assert "Không có tài khoản" in render_verdict(verdict)


def test_a_foreign_number_and_a_bad_record_do_not_raise() -> None:
    assert evaluate_identity(None, phone="+84987654321")["found"] is False
    assert evaluate_identity({"found": True}, full_name=None, cccd=None, phone=None)["found"] is True


class _StubRetrieval:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []
        self.saved: list[dict] = []

    async def call_tingting_api(self, *, method, path, params):  # noqa: ANN001
        from app.services.external_api_core import ExternalApiOutcome

        self.calls.append({"method": method, "path": path, "params": params})
        return ExternalApiOutcome("ok", "TingTing", path, 200, self.text)

    async def save_tingting_flow_state(self, _phone: str, state: dict) -> dict:
        self.saved.append(dict(state))
        return dict(state)


@pytest.mark.asyncio
async def test_the_tool_records_a_verified_phone_as_the_otp_gate() -> None:
    retrieval = _StubRetrieval(
        '{"data":{"found":true,"employee_name":"Nguyễn Việt Dũng","cccd":"11112222",'
        '"mobile":"0357210887"}}'
    )
    result = await verify_tingting_identity(
        retrieval, phone="0357210887", full_name="Nguyen Viet Dung", cccd="11112222"
    )
    assert "ĐÃ XÁC MINH" in result
    assert retrieval.saved == [{"verified": True}]
    assert retrieval.calls[0]["path"] == "/api/v1/integration/employee/lookup"


@pytest.mark.asyncio
async def test_the_tool_does_not_record_an_unverified_phone() -> None:
    retrieval = _StubRetrieval('{"data":{"found":true,"employee_name":"Nguyễn Việt Dũng"}}')
    result = await verify_tingting_identity(retrieval, phone="0357210887", full_name="Trần Văn A")
    assert "CHƯA XÁC MINH" in result
    assert retrieval.saved == []


@pytest.mark.asyncio
async def test_the_tool_needs_a_phone_before_calling_anything() -> None:
    retrieval = _StubRetrieval('{"data":{"found":true}}')
    result = await verify_tingting_identity(retrieval, phone="  ")
    assert "Thiếu số điện thoại" in result
    assert retrieval.calls == []