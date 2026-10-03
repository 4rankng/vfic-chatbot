"""Unit tests for project work-address extraction, grounding, and geocoding.

No DB, no network, no live LLM: the session is a two-method double, the
document repository is monkeypatched at its import site, and the geocoder is
replaced by a recording stub.
"""

from __future__ import annotations

import pytest

from app.services.geo import project_address
from app.services.geo.factory_point import FactoryPoint
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
    def __init__(
        self,
        extracted_address: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        self.id = "11111111-1111-4111-8111-111111111111"
        self.extracted_address = extracted_address
        self.latitude: float | None = latitude
        self.longitude: float | None = longitude


class _Doc:
    def __init__(self, raw_text: str | None) -> None:
        self.raw_text = raw_text


class _Session:
    def __init__(self, project: _Project | None) -> None:
        self.project = project

    async def get(self, _model, _project_id):
        return self.project


class _Resolver:
    """Stands in for ``resolve_factory_point`` — the only thing that may now
    write a project coordinate."""

    def __init__(self, point: tuple[float, float] | None) -> None:
        self.point = point
        self.queries: list[str] = []

    async def __call__(self, address: str, *, providers=None):
        self.queries.append(address)
        if self.point is None:
            return None
        return FactoryPoint(
            point=self.point, provider="google", text=address, matched_anchor="an phong"
        )


class _LLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


@pytest.fixture
def stub_resolver(monkeypatch):
    def _install(point: tuple[float, float] | None = (20.86, 106.68)) -> _Resolver:
        stub = _Resolver(point)
        monkeypatch.setattr(project_address, "resolve_factory_point", stub)
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
async def test_refresh_from_kb_skips_a_resolved_project(stub_resolver, stub_document):
    """"Resolved" means an address AND coordinates. A project that has both is
    left alone — no document read, no model call, no geocoder call. The
    address-but-no-coordinates case is covered separately: it must retry."""
    project = _Project(extracted_address=_ADDRESS, latitude=20.86, longitude=106.68)
    llm = _LLM('{"address": "khác"}')
    resolver = stub_resolver()
    seen = stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert seen["calls"] == 0
    assert llm.calls == []
    assert resolver.queries == []
    assert (project.latitude, project.longitude) == (20.86, 106.68)


@pytest.mark.asyncio
async def test_refresh_from_kb_force_regeocodes_without_calling_the_llm(
    stub_resolver, stub_document
):
    project = _Project(extracted_address=_ADDRESS)
    llm = _LLM('{"address": "khác"}')
    resolver = stub_resolver((20.9, 106.7))
    seen = stub_document(_BRIEF)

    await project_address.refresh_from_kb(
        _Session(project), project.id, llm_json=llm, force=True
    )

    assert seen["calls"] == 0
    assert llm.calls == []
    assert resolver.queries == [_ADDRESS]
    assert (project.latitude, project.longitude) == (20.9, 106.7)


@pytest.mark.asyncio
async def test_refresh_from_kb_extracts_grounds_and_stores(stub_resolver, stub_document):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    resolver = stub_resolver()
    seen = stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert seen["project_id"] == project.id
    assert llm.calls[0][1] == _BRIEF
    assert resolver.queries == [_ADDRESS]
    assert project.extracted_address == _ADDRESS
    assert (project.latitude, project.longitude) == (20.86, 106.68)


@pytest.mark.asyncio
async def test_refresh_from_kb_drops_an_ungrounded_address(stub_resolver, stub_document):
    project = _Project()
    llm = _LLM('{"address": "Lô B2, KCN Nhật Bản, Quận 7, TP. Hồ Chí Minh"}')
    resolver = stub_resolver()
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert resolver.queries == []
    assert project.extracted_address is None
    assert project.latitude is None


@pytest.mark.asyncio
async def test_refresh_from_kb_leaves_the_row_unchanged_when_geocoding_misses(
    stub_resolver, stub_document
):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    resolver = stub_resolver(None)
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert resolver.queries == [_ADDRESS]
    assert project.extracted_address is None
    assert project.latitude is None


@pytest.mark.asyncio
async def test_refresh_from_kb_returns_without_a_document(stub_resolver, stub_document):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    resolver = stub_resolver()
    stub_document(None)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert llm.calls == []
    assert resolver.queries == []


@pytest.mark.asyncio
async def test_refresh_from_kb_survives_a_repository_failure(
    stub_resolver, monkeypatch, caplog
):
    project = _Project()
    llm = _LLM(f'{{"address": "{_ADDRESS}"}}')
    resolver = stub_resolver()

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
    assert resolver.queries == []
    assert project.extracted_address is None


# -------------------------------------------------------- refresh_from_address
@pytest.mark.asyncio
async def test_refresh_from_kb_stores_only_a_verified_point(stub_resolver, stub_document):
    """The coordinate is quoted to a candidate as a road distance, so it comes
    from the VERIFIED resolver — never straight from a geocoder. That is the
    whole fix for the 2026-10-03 incident, where a city centroid was stored as
    KCN Tràng Duệ and reported as "1.5 km" for a plant 13.6 km away."""
    project = _Project()
    resolver = stub_resolver((20.8588, 106.5723))
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(
        _Session(project), project.id, llm_json=_LLM(f'{{"address": "{_ADDRESS}"}}')
    )

    assert resolver.queries == [_ADDRESS]
    assert (project.latitude, project.longitude) == (20.8588, 106.5723)


@pytest.mark.asyncio
async def test_refresh_from_address_stores_only_a_verified_point(stub_resolver):
    project = _Project()
    stub_resolver((20.8588, 106.5723))

    await project_address.refresh_from_address(_Session(project), project.id, "KCN Tràng Duệ")

    assert (project.latitude, project.longitude) == (20.8588, 106.5723)


@pytest.mark.asyncio
async def test_a_rejected_address_leaves_the_row_untouched(stub_resolver, stub_document):
    """No verified point means no coordinates AND no address: a project the
    system cannot place must not look like one it placed at the city centre."""
    project = _Project()
    stub_resolver(None)
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(
        _Session(project), project.id, llm_json=_LLM(f'{{"address": "{_ADDRESS}"}}')
    )

    assert project.latitude is None
    assert project.longitude is None
    assert project.extracted_address is None


@pytest.mark.asyncio
async def test_refresh_from_kb_regeocodes_an_address_that_never_got_coordinates(
    stub_resolver, stub_document
):
    """An address without coordinates is re-geocoded on the next pass.

    Before this, the presence of ``extracted_address`` short-circuited every
    re-ingest, so a single transient miss — or the new gate refusing a centroid —
    froze the project permanently: nothing else would ever fill the gap.
    """
    project = _Project(extracted_address=_ADDRESS)
    assert project.latitude is None
    resolver = stub_resolver((20.86, 106.68))
    llm = _LLM('{"address": "khác"}')
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(_Session(project), project.id, llm_json=llm)

    assert resolver.queries == [_ADDRESS]
    assert llm.calls == []  # the stored address is still the cache: no re-extraction
    assert (project.latitude, project.longitude) == (20.86, 106.68)


@pytest.mark.asyncio
async def test_refresh_from_kb_leaves_a_placed_project_alone(stub_resolver, stub_document):
    """The counterpart: once a project HAS coordinates, a re-ingest must not
    spend a geocoder call re-resolving it."""
    project = _Project(extracted_address=_ADDRESS, latitude=20.86, longitude=106.68)
    resolver = stub_resolver()
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(
        _Session(project), project.id, llm_json=_LLM('{"address": "khác"}')
    )

    assert resolver.queries == []


@pytest.mark.asyncio
async def test_project_geocode_survives_unreadable_credentials(
    stub_resolver, stub_document, monkeypatch
):
    """Credentials are decoration. A read failure degrades to the keyless chain
    and still places the project — it must not fail the caller's write."""
    project = _Project()
    resolver = stub_resolver()

    class _Boom:
        def __init__(self, _db) -> None: ...

        async def resolve_geocoder(self):
            raise RuntimeError("settings table unreachable")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService", _Boom, raising=False
    )
    stub_document(_BRIEF)

    await project_address.refresh_from_kb(
        _Session(project), project.id, llm_json=_LLM(f'{{"address": "{_ADDRESS}"}}')
    )

    assert resolver.queries == [_ADDRESS]
    assert (project.latitude, project.longitude) == (20.86, 106.68)


@pytest.mark.asyncio
async def test_refresh_from_address_stores_a_human_authored_address(stub_resolver):
    project = _Project()
    resolver = stub_resolver((20.86, 106.68))

    await project_address.refresh_from_address(
        _Session(project), project.id, "KCN Tràng Duệ, An Dương, Hải Phòng"
    )

    assert resolver.queries == ["KCN Tràng Duệ, An Dương, Hải Phòng"]
    assert project.extracted_address == "KCN Tràng Duệ, An Dương, Hải Phòng"
    assert (project.latitude, project.longitude) == (20.86, 106.68)


@pytest.mark.asyncio
async def test_refresh_from_address_defers_to_a_pipeline_resolved_project(stub_resolver):
    project = _Project(extracted_address=_ADDRESS)
    resolver = stub_resolver()

    await project_address.refresh_from_address(_Session(project), project.id, "Hải Phòng")

    assert resolver.queries == []
    assert project.extracted_address == _ADDRESS


@pytest.mark.asyncio
async def test_refresh_from_address_ignores_an_empty_value(stub_resolver):
    project = _Project()
    resolver = stub_resolver()

    await project_address.refresh_from_address(_Session(project), project.id, "   ")

    assert resolver.queries == []
