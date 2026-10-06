"""The deterministic (regex) tier of lead extraction.

Closed-shape fields only: age, birth year and salary are read straight from
the candidate's message on the inbound path, before any queue or model can
fail. Everything open-ended deliberately stays with the LLM — these pins guard
both the captures and the NON-captures, because a wrong salary a recruiter
dials against is worse than a blank one.
"""

from __future__ import annotations

from app.services.lead.normalizers import deterministic_lead_details


def test_age_and_birth_year_are_read_from_the_message() -> None:
    assert deterministic_lead_details("mình 28 tuổi") == {"age": 28}
    assert deterministic_lead_details("Em 25 tuoi") == {"age": 25}
    assert deterministic_lead_details("sinh 1998") == {"birth_year": 1998}
    assert deterministic_lead_details("sn 1981, ở Hải Phòng") == {"birth_year": 1981}
    assert deterministic_lead_details("mình 28 tuổi, sn 1998") == {
        "age": 28,
        "birth_year": 1998,
    }


def test_noise_never_becomes_an_age() -> None:
    for text in (
        "khoảng 28 người",
        "chờ 28 phút",
        "đã 1.280 km",
        "họ có 30 năm kinh nghiệm",  # no "tuổi"
        "xin chào",
    ):
        assert "age" not in deterministic_lead_details(text), text


def test_age_bounds_live_in_normalize_lead_not_in_the_pattern() -> None:
    """The regex only finds a number; the 15..80 contract stays in one place.

    "12 tuổi thì làm được chưa" reads as an age here and is then rejected by
    ``normalize_lead`` — a second copy of the bound in the pattern would be a
    second place to drift.
    """
    from app.services.lead.normalizers import normalize_lead

    assert deterministic_lead_details("12 tuổi thì làm được chưa") == {"age": 12}
    patch = normalize_lead({"age": 12}, "zalo_1")
    assert patch is not None
    assert patch["age"] is None
    assert normalize_lead({"age": 28}, "zalo_1")["age"] == 28


def test_salary_needs_a_salary_keyword() -> None:
    # A bare number is ambiguous: no keyword, no write (the LLM still sees it).
    assert deterministic_lead_details("12 triệu đồng") == {}
    assert deterministic_lead_details("muốn nhận 15 tr") == {}
    # With the keyword, the common Vietnamese shapes all land:
    assert deterministic_lead_details("lương mong muốn 12 triệu") == {
        "expected_salary": "12 triệu"
    }
    assert deterministic_lead_details("mức lương 12-14 triệu") == {
        "expected_salary": "12-14 triệu"
    }
    assert deterministic_lead_details("thu nhập 12tr5") == {
        "expected_salary": "12.5 triệu"
    }
    assert deterministic_lead_details("lương 12.000.000") == {
        "expected_salary": "12.000.000"
    }
    assert deterministic_lead_details("luong 9 trieu") == {"expected_salary": "9 triệu"}


def test_combined_message_returns_every_stated_field() -> None:
    assert deterministic_lead_details(
        "mình 25 tuổi, lương mong muốn 10-12 triệu, sn 2001"
    ) == {
        "age": 25,
        "birth_year": 2001,
        "expected_salary": "10-12 triệu",
    }


def test_empty_and_none_inputs_write_nothing() -> None:
    assert deterministic_lead_details("") == {}
    assert deterministic_lead_details(None) == {}
