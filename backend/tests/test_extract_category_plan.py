"""Any-txt ingestion: the digest LLM maps prose into category writes."""

from __future__ import annotations

from app.services.knowledge.extraction import extract_category_plan


class _FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.payload


_JOBS = (
    '{"jobs": [{"id": "nhan-vien-lap-rap", "title": "Nhân viên lắp ráp", '
    '"aliases": [], "location": "Hải Phòng", '
    '"summary": "Lắp ráp linh kiện điện tử.", "keywords": []}]}'
)

_CONTACTS = (
    '{"contacts": [{"id": "lien-he", "name": "Cường", "role": "Cán bộ hồ sơ", '
    '"phone": "0859256588", "zalo": "0859256588", "email": null, '
    '"address": "KCN Vsip", "working_hours": null, "notes": "Đón tiếp"}]}'
)


async def test_maps_prose_into_rendered_category_writes():
    llm = _FakeLLM(_JOBS[:-1] + "," + _CONTACTS[1:])

    plan = await extract_category_plan("Phiếu thông tin dự án bất kỳ.", llm)

    assert plan is not None
    assert [write.key.value for write in plan.writes] == ["jobs", "contacts"]
    jobs, contacts = plan.writes
    assert jobs.filename == "jobs.md"
    assert "category: jobs" in jobs.content
    assert "### record: nhan-vien-lap-rap" in jobs.content
    assert "0859256588" in contacts.content
    # The prompt names the categories and the raw text reaches the model.
    assert "Danh mục:" in llm.calls[0][0]
    assert "Phiếu thông tin dự án bất kỳ." in llm.calls[0][1]


async def test_junk_category_skips_without_failing_the_import():
    llm = _FakeLLM(
        '{"contacts": [{"nonsense": true}], ' + _JOBS[1:]
    )

    plan = await extract_category_plan("nội dung", llm)

    assert plan is not None
    assert [write.key.value for write in plan.writes] == ["jobs"]


async def test_unusable_extraction_returns_none_for_plain_ingestion():
    for payload in ("not json", "{}", '{"jobs": []}', "[]"):
        assert await extract_category_plan("nội dung", _FakeLLM(payload)) is None


async def test_llm_failure_returns_none_rather_than_raising():
    class _Exploding:
        async def __call__(self, system, user):
            raise RuntimeError("provider down")

    assert await extract_category_plan("nội dung", _Exploding()) is None
