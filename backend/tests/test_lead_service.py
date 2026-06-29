"""US-007 LeadExtractionService tests: verbatim normalization + COALESCE upsert
(never overwrite a non-null existing value with null/empty)."""
import pytest

from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services.lead_service import (
    LeadExtractionService,
    lead_profile_text,
    normalize_integer,
    normalize_lead,
    normalize_lead_score,
    normalize_phone,
    parse_lead_json,
)

pytestmark = pytest.mark.asyncio


def _lead(**over) -> dict:
    base = dict.fromkeys(
        ["zalo_id", "name", "phone", "birth_year", "age", "living_area", "address",
         "gender", "region", "desired_job", "years_experience", "latest_company",
         "expected_salary", "lead_score"],
        None,
    )
    base.update(over)
    return base


def test_normalize_phone_vi():
    assert normalize_phone("0912345678") == "0912345678"
    assert normalize_phone("+84912345678") == "0912345678"
    assert normalize_phone("abc") is None
    assert normalize_phone("123") is None


def test_normalize_integer_and_score():
    assert normalize_integer("25", 15, 80) == 25
    assert normalize_integer("5", 15, 80) is None  # below range
    assert normalize_lead_score("HOT", None) == "hot"
    assert normalize_lead_score("x", "0912345678") == "hot"  # phone => hot
    assert normalize_lead_score("x", None) is None


def test_parse_lead_json_fenced():
    assert parse_lead_json("```json\n{\"name\":\"Dũng\"}\n```") == {"name": "Dũng"}
    assert parse_lead_json("no json") == {}


def test_normalize_lead_requires_chat_id():
    assert normalize_lead('{"name":"x"}', None) is None
    lead = normalize_lead('{"name":"Dũng","phone":"0912345678"}', "z-1")
    assert lead["zalo_id"] == "z-1" and lead["name"] == "Dũng" and lead["phone"] == "0912345678"


async def test_upsert_coalesce_keeps_existing(db_session):
    conv = Conversation(zalo_chat_id="lead-1")
    db_session.add(conv)
    await db_session.commit()

    id1 = await LeadExtractionService.upsert(db_session, _lead(zalo_id="lead-1", name="Dũng", phone="0912345678", lead_score="hot"))
    # second upsert (same zalo_id): name empty -> must NOT clobber "Dũng"; region is new -> added
    id2 = await LeadExtractionService.upsert(db_session, _lead(zalo_id="lead-1", name="", region="Hải Phòng"))
    assert id1 == id2

    row = await db_session.get(Lead, id1)
    assert row.name == "Dũng"          # COALESCE kept the existing value
    assert row.region == "Hải Phòng"   # new non-empty value applied
    assert row.lead_score == "hot"     # preserved


# --- lead_profile_text tests ---


def test_lead_profile_text_none_returns_new_user():
    out = lead_profile_text(None)
    assert "mới, chưa có dữ liệu" in out
    assert "chưa có" in out
    # name should appear first (highest priority)
    lines = [line for line in out.split("\n") if line.startswith("-")]
    assert lines[0].startswith("- Tên:")
    assert lines[1].startswith("- Số điện thoại:")


def test_lead_profile_text_empty_dict_returns_new_user():
    out = lead_profile_text({})
    assert "mới, chưa có dữ liệu" in out


def test_lead_profile_text_partial_lead():
    lead = {"name": "Dũng", "phone": "0912345678", "desired_job": None, "region": "Hải Phòng", "living_area": None, "years_experience": "2 năm"}
    out = lead_profile_text(lead)
    assert "Dũng" in out
    assert "0912345678" in out
    assert "Hải Phòng" in out
    assert "chưa có" in out  # desired_job is None


def test_lead_profile_text_full_lead():
    lead = {"name": "Lê Chân", "phone": "0357210887", "desired_job": "Công nhân", "region": "Hải Phòng", "living_area": "Quận 7", "years_experience": "3"}
    out = lead_profile_text(lead)
    assert "chưa có" not in out
    assert "Lê Chân" in out
    assert "0357210887" in out
    assert "Công nhân" in out


def test_lead_profile_text_no_double_suffix():
    """LLM stores years_experience as free-form text like '2 năm' — no double suffix."""
    lead = {"name": "An", "years_experience": "2 năm làm kho", "phone": "0912345678",
            "desired_job": None, "region": None, "living_area": None}
    out = lead_profile_text(lead)
    assert "năm năm" not in out
    assert "2 năm làm kho" in out
