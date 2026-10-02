"""Unit tests for project work-address extraction, grounding, and geocoding.

No DB, no network, no live LLM: the session is a two-method double, the
document repository is monkeypatched at its import site, and the geocoder is
replaced by a recording stub.
"""

from __future__ import annotations

import pytest

from app.services.geo import project_address
from app.services.knowledge.prompts import ADDRESS_EXTRACTION_SYSTEM_PROMPT

_BRIEF = """\
DỰ ÁN 4P — LG ELECTRONICS

Địa chỉ làm việc: Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong,
An Dương, Hải Phòng
Mức lương: 7.500.000 - 9.000.000 VND/tháng
Địa chỉ liên hệ: Manhattan 07-08, Vinhomes Imperia, Hồng Bàng, Hải Phòng
"""

_ADDRESS = (
    "Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"
)


class _Project:
    def __init__(self, extracted_address: str | None = None) -> None:
        self.id = "11111111-1111-4111-8111-111111111111"
        self.extracted_address = extracted_address
        self.latitude: float | None = None
        self.longitude: float | None = None


class _Doc:
    def __init__(self, raw_text: str | None) -> None:
        self.raw_text = raw_text


class _Session:
    def __init__(self, project: _Project | None) -> None:
        self.project = project

    async def get(self, _model, _project_id):
        return self.project


class _Geocoder:
    def __init__(self, coords: tuple[float, float] | None) -> None:
        self.coords = coords
        self.queries: list[str] = []

    async def __call__(self, query: str):
        self.queries.append(query)
        return self.coords


class _LLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


@pytest.fixture
def stub_geocode(monkeypatch):
    def _install(coords: tuple[float, float] | None = (20.86, 106.68)) -> _Geocoder:
        stub = _Geocoder(coords)
        monkeypatch.setattr(project_address, "geocode", stub)
        return stub

    return _install


@pytest.fixture
def stub_document(monkeypatch):
    """Patch the repository ``refresh_from_kb`` imports lazily."""

    def _install(raw_text: str | None) -> dict:
        seen: dict = {"calls": 0, "project_id": None}

        class _Repo:
            def __init__(self, _db) -> None: ...

            async def get_latest_document_with_text(self, project_id):
                seen["calls"] += 1
                seen["project_id"] = project_id
                return _Doc(raw_text)

        monkeypatch.setattr(
            "app.services.project.repository.ProjectRepository", _Repo, raising=False
        )
        return seen

    return _install


# --------------------------------------------------------------------- grounding
def test_ground_address_accepts_an_address_the_brief_contains():
    assert project_address.ground_address(_ADDRESS, _BRIEF) == _ADDRESS


def test_ground_address_rejects_a_fabricated_district():
    fabricated = "Lô B2, KCN Nhật Bản, Quận 7, TP. Hồ Chí Minh"
    assert project_address.ground_address(fabricated, _BRIEF) is None


def test_ground_address_rejects_an_empty_address():
    assert project_address.ground_address("", _BRIEF) is None
    assert project_address.ground_address("  ,  ", _BRIEF) is None


# ---------------------------------------------------------------- extraction
@pytest.mark.asyncio
async def test_extract_project_address_reads_the_json_field():
    llm = _LLM('{"address": "  KCN Tràng Duệ, An Dương, Hải Phòng  "}')

    assert (
        await project_address.extract_project_address(llm, _BRIEF)
        == "KCN Tràng Duệ, An Dương, Hải Phòng"
    )
    assert llm.calls == [(ADDRESS_EXTRACTION_SYSTEM_PROMPT, _BRIEF)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    ['{"address": null}', '{"address": 12}', '{"address": ""}', "{}", "<<<not json>>>", ""],
)
async def test_extract_project_address_tolerates_null_non_str_and_bad_json(raw):
    assert await project_address.extract_project_address(_LLM(raw), _BRIEF) is None


@pytest.mark.asyncio
async def test_extract_project_address_survives_a_provider_failure():
    class _Boom:
        async def __call__(self, system, user):
            raise RuntimeError("provider down")

    assert await project_address.extract_project_address(_Boom(), _BRIEF) is None


# ------------------------------------------------------------- refresh_from_kb
@pytest.mark.asyncio
async def test_refresh_from_kb_skips_a_resolved_project(stub_geocode, stub_document):
    project = _Project(extracted_address=_ADDRESS)
    llm = _LLM('{"address": "khác"}')
    geocoder = stub_geocode()
    seen = stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert seen["calls"] == 0
    assert llm.calls == []
    assert geocoder.queries == []
    assert project.latitude is None


@pytest.mark.asyncio
async def test_refresh_from_kb_force_regeocodes_without_calling_the_llm(
    stub_geocode, stub_document
):
    project = _Project(extracted_address=_ADDRESS)
    llm = _LLM('{"address": "khác"}')
    geocoder = stub_geocode((20.9, 106.7))
    seen = stub_document(_BRIEF)

    await project_address.refresh_from_kb(
        _Session(project), project.id, llm_json=llm, force=True
    )

    assert seen["calls"] == 0
    assert llm.calls == []
    assert geocoder.queries == [_ADDRESS]
    assert (project.latitude, project.longitude) == (20.9, 106.7)


@pytest.mark.asyncio
async def test_refresh_from_kb_extracts_grounds_and_stores(stub_geocode, stub_document):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    geocoder = stub_geocode()
    seen = stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert seen["project_id"] == project.id
    assert llm.calls[0][1] == _BRIEF
    assert geocoder.queries == [_ADDRESS]
    assert project.extracted_address == _ADDRESS
    assert (project.latitude, project.longitude) == (20.86, 106.68)


@pytest.mark.asyncio
async def test_refresh_from_kb_drops_an_ungrounded_address(stub_geocode, stub_document):
    project = _Project()
    llm = _LLM('{"address": "Lô B2, KCN Nhật Bản, Quận 7, TP. Hồ Chí Minh"}')
    geocoder = stub_geocode()
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert geocoder.queries == []
    assert project.extracted_address is None
    assert project.latitude is None


@pytest.mark.asyncio
async def test_refresh_from_kb_leaves_the_row_unchanged_when_geocoding_misses(
    stub_geocode, stub_document
):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    geocoder = stub_geocode(None)
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert geocoder.queries == [_ADDRESS]
    assert project.extracted_address is None
    assert project.latitude is None


@pytest.mark.asyncio
async def test_refresh_from_kb_returns_without_a_document(stub_geocode, stub_document):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    geocoder = stub_geocode()
    stub_document(None)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert llm.calls == []
    assert geocoder.queries == []


@pytest.mark.asyncio
async def test_refresh_from_kb_survives_a_repository_failure(
    stub_geocode, monkeypatch, caplog
):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    geocoder = stub_geocode()

    class _Boom:
        def __init__(self, _db) -> None: ...

        async def get_latest_document_with_text(self, _project_id):
            raise RuntimeError("database down")

    monkeypatch.setattr(
        "app.services.project.repository.ProjectRepository", _Boom, raising=False
    )

    with caplog.at_level("WARNING", logger="app.services.geo.project_address"):
        await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert "database down" in caplog.text
    assert geocoder.queries == []
    assert project.extracted_address is None


# -------------------------------------------------------- refresh_from_address
@pytest.mark.asyncio
async def test_refresh_from_address_stores_a_human_authored_address(stub_geocode):
    project = _Project()
    geocoder = stub_geocode((20.86, 106.68))

    await project_address.refresh_from_address(
        _Session(project), project.id, "KCN Tràng Duệ, An Dương, Hải Phòng"
    )

    assert geocoder.queries == ["KCN Tràng Duệ, An Dương, Hải Phòng"]
    assert project.extracted_address == "KCN Tràng Duệ, An Dương, Hải Phòng"
    assert (project.latitude, project.longitude) == (20.86, 106.68)


@pytest.mark.asyncio
async def test_refresh_from_address_defers_to_a_pipeline_resolved_project(stub_geocode):
    project = _Project(extracted_address=_ADDRESS)
    geocoder = stub_geocode()

    await project_address.refresh_from_address(_Session(project), project.id, "Hải Phòng")

    assert geocoder.queries == []
    assert project.extracted_address == _ADDRESS


@pytest.mark.asyncio
async def test_refresh_from_address_ignores_an_empty_value(stub_geocode):
    project = _Project()
    geocoder = stub_geocode()

    await project_address.refresh_from_address(_Session(project), project.id, "   ")

    assert geocoder.queries == []
