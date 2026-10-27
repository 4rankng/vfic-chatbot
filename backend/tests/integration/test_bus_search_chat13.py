"""CHAT-13 database proof: "cho hỏi dự án Lear có đưa đón không" must surface
the project's KB route — stops without times and the route's Ghi chú included.

The production shape this pins: the company row carries an import placeholder
name ("Dự án mới") while the candidate-facing project is "Lear Cát Hải", the
route's four KB stops have no scheduled times, and the pickup condition lives
in ``bus_routes.notes``. All three used to fall through the timetable search
and the bot answered "tin tuyển dụng chưa ghi rõ".
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from app.models.bus import BusRoute, BusStop
from app.models.company import Company, Project
from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.retrieval.timetable_repository import TimetableRepository

pytestmark = pytest.mark.integration

_GHI_CHU = (
    "Các địa điểm khác như an lão, an dương, tiên lãng phải gom đủ 5 người trở lên "
    "mới điều xe đón."
)
_QUESTION = "cho hỏi dự án Lear có đưa đón không"


async def _seed_learner_project(session) -> tuple[Project, BusRoute]:
    project = Project(
        name="Lear Cát Hải",
        slug=f"du-an-moi-{uuid.uuid4().hex[:8]}",
        category_authority_started=True,
        index_card={},
    )
    session.add(project)
    await session.flush()
    company = Company(project_id=project.id, name="Dự án mới")
    session.add(company)
    await session.flush()
    category = KnowledgeCategory(
        project_id=project.id,
        category_key=KnowledgeCategoryKey.TRANSPORTATION.value,
    )
    session.add(category)
    await session.flush()
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=1,
        status=KnowledgeCategoryRevisionStatus.ACTIVE,
        source_filename="transportation.md",
        source_markdown="## transportation",
        normalized_payload={},
        content_sha256=hashlib.sha256(f"transportation-{uuid.uuid4()}".encode()).hexdigest(),
    )
    session.add(revision)
    await session.flush()
    route = BusRoute(
        project_id=project.id,
        company_id=company.id,
        source_category_revision_id=revision.id,
        route_name="Xe đưa đón",
        route_no=revision.id.hex,
        route_variant=f"auto-transportation-{uuid.uuid4().hex[:24]}",
        shift="day",
        direction="outbound",
        mode="company_bus",
        source_page="category_markdown",
        notes=_GHI_CHU,
        route_group_key=revision.id.hex,
    )
    session.add(route)
    await session.flush()
    for index, stop in enumerate(
        ("Đồ sơn", "Thư viện thành phố", "Nhà thi đấu kiến thụy", "Bến xe thượng lý"),
        start=1,
    ):
        session.add(BusStop(route_id=route.id, stop_order=index, stop_name=stop))
    await session.flush()
    return project, route


@pytest.mark.asyncio
async def test_project_name_and_noteless_question_surface_the_route(integration_session):
    _, _route = await _seed_learner_project(integration_session)
    repo = TimetableRepository(integration_session)
    rows = await repo.search_bus_timetable("Lear Cát Hải", _QUESTION, 50)
    assert rows, "the Lear route must surface for the đưa đón question"
    mappings = [dict(row._mapping) for row in rows]
    assert all(m["company_name"] == "Dự án mới" for m in mappings)
    assert mappings[0]["route_name"] == "Xe đưa đón"
    assert mappings[0]["notes"] == _GHI_CHU
    stops = [m["stop_name"] for m in mappings]
    assert stops == [
        "Đồ sơn",
        "Thư viện thành phố",
        "Nhà thi đấu kiến thụy",
        "Bến xe thượng lý",
    ]
    assert all(not m["scheduled_time"] for m in mappings)


@pytest.mark.asyncio
async def test_partial_project_name_still_resolves(integration_session):
    _, _route = await _seed_learner_project(integration_session)
    repo = TimetableRepository(integration_session)
    rows = await repo.search_bus_timetable("Lear", _QUESTION, 50)
    assert rows, "the project-name match must also resolve the bare alias 'Lear'"
    assert dict(rows[0]._mapping)["route_name"] == "Xe đưa đón"


@pytest.mark.asyncio
async def test_timeless_stops_match_by_route_token(integration_session):
    """Route-name tokens in the question count even without stop times."""
    _, _route = await _seed_learner_project(integration_session)
    repo = TimetableRepository(integration_session)
    rows = await repo.search_bus_timetable("Dự án mới", "có xe đưa đón không vậy", 50)
    assert rows, "route-token match must find the route by its own name"


@pytest.mark.asyncio
async def test_timed_routes_and_company_names_still_match(integration_session):
    """Regression: the pre-CHAT-13 match paths keep working."""
    project = Project(
        name="Legacy Bus Co",
        slug=f"legacy-bus-{uuid.uuid4().hex[:8]}",
        category_authority_started=False,
        index_card={},
    )
    session = integration_session
    session.add(project)
    await session.flush()
    company = Company(project_id=project.id, name="Legacy Bus Co")
    session.add(company)
    await session.flush()
    route = BusRoute(
        project_id=project.id,
        company_id=company.id,
        route_name="Hà Nội",
        route_variant="legacy",
        shift="day",
        direction="outbound",
        source_page="legacy.md",
        route_group_key="ha-noi",
    )
    session.add(route)
    await session.flush()
    from datetime import time

    session.add(
        BusStop(
            route_id=route.id,
            stop_order=1,
            stop_name="Sài Đồng",
            stop_aliases=["sài đồng"],
            scheduled_time=time(6, 30),
        )
    )
    await session.flush()
    repo = TimetableRepository(session)
    rows = await repo.search_bus_timetable("Legacy Bus Co", "xe sang sài đồng mấy giờ", 50)
    assert rows
    mapping = dict(rows[0]._mapping)
    assert mapping["stop_name"] == "Sài Đồng"
    assert mapping["scheduled_time"] == "06:30"
