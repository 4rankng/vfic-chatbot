"""The three-try identity-verification cap and the gender-aware verdict.

Covers the two behavior changes on ``verify_tingting_identity``:

- a wrong answer spends one of three tries; the third stops the flow with the
  dictated reply whose tail points at the hotline — nothing is queued
  (operator rule 2026-09-29), and only a verified match clears the counter;
- the verdict derives the address form (anh/chị) from the name the EMPLOYEE
  typed, never from the lookup record (the record is the answer key).
"""

from __future__ import annotations

import pytest

from app.graph.tools.tingting_identity import verify_tingting_identity
from app.graph.tingting_guide import (
    tingting_api_guide,
    tingting_hotline_reply,
    tingting_verify_exhausted_reply,
)
from app.shared.domain.vietnamese_gender import infer_gender_from_name

# The persona/guide/replies are built around the stored hotline setting; the
# stub serves the owner-approved number (the value Alembic 0058 seeds).
TINGTING_HOTLINE = "+84 914 827 988"
TINGTING_API_GUIDE = tingting_api_guide(TINGTING_HOTLINE)
TINGTING_HOTLINE_REPLY = tingting_hotline_reply(TINGTING_HOTLINE)
TINGTING_VERIFY_EXHAUSTED_REPLY = tingting_verify_exhausted_reply(TINGTING_HOTLINE)

_SCOPE = "0f9b1c3e-1111-4222-8333-444455556666"
_FOUND_RECORD = (
    '{"data":{"found":true,"employee_name":"Nguyễn Văn B","cccd":"11112222",'
    '"mobile":"0357210887"}}'
)
_NOT_FOUND_RECORD = '{"data":{"found":false}}'


class _CountingRetrieval:
    """Port stub that counts failures toward the exhaustion cap."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.failures = 0
        self.cleared = 0

    async def call_tingting_api(self, *, method, path, params):  # noqa: ANN001
        from app.services.external_api_core import ExternalApiOutcome

        return ExternalApiOutcome("ok", "TingTing", path, 200, self.text)

    async def save_tingting_flow_state(self, _phone: str, state: dict) -> dict:
        return dict(state)

    async def tingting_verify_attempts(self, scope: str) -> int:  # noqa: ARG002
        return self.failures

    async def record_tingting_verify_failure(self, scope: str) -> int:  # noqa: ARG002
        self.failures += 1
        return self.failures

    async def clear_tingting_verify_attempts(self, scope: str) -> None:  # noqa: ARG002
        self.cleared += 1

    async def tingting_hotline(self) -> str:  # noqa: ARG002
        return TINGTING_HOTLINE


@pytest.mark.asyncio
async def test_three_wrong_submissions_exhaust_and_flag_the_conversation() -> None:
    retrieval = _CountingRetrieval(_NOT_FOUND_RECORD)
    for _ in range(2):
        result = await verify_tingting_identity(
            retrieval,
            phone="0900000001",
            conversation_scope=_SCOPE,
        )
        assert "THÔNG TIN KHÔNG HỢP LỆ" not in result
    exhausted = await verify_tingting_identity(
        retrieval,
        phone="0900000001",
        conversation_scope=_SCOPE,
    )
    assert "THÔNG TIN KHÔNG HỢP LỆ" in exhausted
    assert TINGTING_VERIFY_EXHAUSTED_REPLY in exhausted
    assert exhausted.rstrip().endswith("không hướng dẫn gì thêm.")
    assert retrieval.failures == 3


@pytest.mark.asyncio
async def test_the_exhaustion_reply_points_at_the_tingting_hotline() -> None:
    """The hotline tail IS the handoff (operator rule 2026-09-29) — no queue write.

    The words must not drift: the number and the shared tail are what the
    employee acts on.
    """
    assert TINGTING_VERIFY_EXHAUSTED_REPLY.endswith(TINGTING_HOTLINE_REPLY)
    assert "914827988" in TINGTING_VERIFY_EXHAUSTED_REPLY.replace(" ", "")
    # The guide quotes the same fixed words, so the model's reply and the
    # tool's verdict can never disagree about what exhaustion sounds like.
    assert TINGTING_VERIFY_EXHAUSTED_REPLY in TINGTING_API_GUIDE


@pytest.mark.asyncio
async def test_a_progression_ask_does_not_spend_a_try() -> None:
    """Record found + matching name + CCCD still owed: guidance, not a failure."""
    retrieval = _CountingRetrieval(_FOUND_RECORD)
    result = await verify_tingting_identity(
        retrieval,
        phone="0357210887",
        full_name="Nguyen Van B",
        conversation_scope=_SCOPE,
    )
    assert "CHƯA XÁC MINH" in result
    assert retrieval.failures == 0


@pytest.mark.asyncio
async def test_a_verified_match_clears_the_counter() -> None:
    retrieval = _CountingRetrieval(_FOUND_RECORD)
    result = await verify_tingting_identity(
        retrieval,
        phone="0357210887",
        full_name="Nguyen Van B",
        cccd="11112222",
        conversation_scope=_SCOPE,
    )
    assert "ĐÃ XÁC MINH" in result
    assert retrieval.cleared == 1


@pytest.mark.asyncio
async def test_without_a_scope_the_cap_never_engages() -> None:
    """Legacy/test port surface: no scope, no counting, plain verdict."""
    retrieval = _CountingRetrieval(_NOT_FOUND_RECORD)
    for _ in range(5):
        result = await verify_tingting_identity(retrieval, phone="0900000001")
        assert "THÔNG TIN KHÔNG HỢP LỆ" not in result
    assert retrieval.failures == 0


@pytest.mark.asyncio
async def test_the_gender_line_comes_from_the_submitted_name_only() -> None:
    """A mismatched name still yields the address form; the record never speaks."""
    retrieval = _CountingRetrieval(_FOUND_RECORD)
    result = await verify_tingting_identity(
        retrieval,
        phone="0357210887",
        full_name="Nguyễn Việt Dũng",
        conversation_scope=_SCOPE,
    )
    assert "giới tính (suy đoán từ tên người dùng tự cung cấp): nam" in result
    assert "«anh»" in result
    assert "Nguyễn Văn B" not in result  # the record's name is never echoed
    # A wrong answer still spent a try even though the gender was inferred.
    assert retrieval.failures == 1


def test_infer_gender_from_name_is_conservative() -> None:
    assert infer_gender_from_name("Nguyễn Việt Dũng") == "male"
    assert infer_gender_from_name("Nguyễn Văn Toàn") == "male"
    assert infer_gender_from_name("Nguyễn Thị Mai") == "female"
    assert infer_gender_from_name("Trần Hằng") == "female"
    # Toneless "dung" is the female given name; "Dũng" carries the tone that
    # makes it male — the collision is why the sets keep tone marks.
    assert infer_gender_from_name("Nguyễn Dung") == "female"
    assert infer_gender_from_name("Frank Ng") == ""
    assert infer_gender_from_name("Nguyễn Bình") == "male"
    assert infer_gender_from_name("") == ""
    # The middle marker wins even when the given name is unlisted.
    assert infer_gender_from_name("Phạm Thị Gia Lai") == "female"
    assert infer_gender_from_name("Lê Văn Đức") == "male"
