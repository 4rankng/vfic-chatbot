"""Phase 3 characterization tests for ProjectService (direct service-level).

Locks the behavior moved out of the projects router: create, slug-collision 409, update,
and list. The worker product-feature read/edit + re-extract paths are already covered
end-to-end by tests/test_product_features.py.
"""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.models.user import User
from app.schemas.projects import ProjectCreate, ProjectUpdate
from app.services.project_service import ProjectService
from tests.conftest import ADMIN_EMAIL

pytestmark = pytest.mark.asyncio


async def _admin(db_session) -> User:
    return (await db_session.scalars(select(User).where(User.email == ADMIN_EMAIL))).first()


async def test_create_update_list(db_session, seed):
    db = db_session
    admin = await _admin(db)
    svc = ProjectService(db)

    created = await svc.create(
        ProjectCreate(slug=f"u-{uuid.uuid4().hex[:4]}", name="Original", is_active=True), admin
    )
    assert created.id is not None

    updated = await svc.update(created.id, ProjectUpdate(name="Renamed"), admin)
    assert updated.name == "Renamed"

    rows = await svc.list()
    assert any(r.id == created.id for r in rows)


async def test_create_slug_collision_returns_409(db_session, seed):
    db = db_session
    admin = await _admin(db)
    svc = ProjectService(db)
    slug = f"dup-{uuid.uuid4().hex[:4]}"

    await svc.create(ProjectCreate(slug=slug, name="First", is_active=True), admin)
    with pytest.raises(HTTPException) as exc:
        await svc.create(ProjectCreate(slug=slug, name="Second", is_active=True), admin)
    assert exc.value.status_code == 409


async def test_create_same_name_returns_existing_project(db_session, seed):
    db = db_session
    admin = await _admin(db)
    svc = ProjectService(db)

    first = await svc.create(
        ProjectCreate(slug="u-a1b2", name="Duplicate Project", is_active=True), admin
    )
    second = await svc.create(
        ProjectCreate(slug="u-d4e5", name="  duplicate project  ", is_active=True), admin
    )

    assert second.id == first.id
    rows = [row for row in await svc.list() if row.name.lower() == "duplicate project"]
    assert len(rows) == 1
    assert rows[0].slug == "u-a1b2"


async def test_update_unknown_project_returns_404(db_session, seed):
    db = db_session
    admin = await _admin(db)
    with pytest.raises(HTTPException) as exc:
        await ProjectService(db).update(uuid.uuid4(), ProjectUpdate(name="x"), admin)
    assert exc.value.status_code == 404


async def test_list_bus_timetable_is_paginated(db_session, seed):
    db = db_session
    admin = await _admin(db)
    project = await ProjectService(db).create(
        ProjectCreate(slug=f"p-{uuid.uuid4().hex[:4]}", name="Bus Paging", is_active=True),
        admin,
    )
    company_id = (
        await db.execute(
            text(
                "INSERT INTO companies(project_id, name) "
                "VALUES (:pid, 'Bus Paging Co') RETURNING id"
            ),
            {"pid": str(project.id)},
        )
    ).scalar()
    for i, route_name in enumerate(["A Route", "B Route", "C Route"], start=1):
        route_id = (
            await db.execute(
                text(
                    "INSERT INTO bus_routes("
                    "project_id, company_id, route_name, route_no, shift, direction, route_group_key"
                    ") VALUES (:pid, :cid, :name, :no, 'day', 'outbound', :key) RETURNING id"
                ),
                {
                    "pid": str(project.id),
                    "cid": str(company_id),
                    "name": route_name,
                    "no": f"0{i}",
                    "key": f"route-{i}",
                },
            )
        ).scalar()
        await db.execute(
            text(
                "INSERT INTO bus_stops(route_id, stop_order, stop_name, scheduled_time) "
                "VALUES (:rid, 1, :stop, '07:00')"
            ),
            {"rid": str(route_id), "stop": f"Stop {i}"},
        )
    await db.commit()

    page_1 = await ProjectService(db).list_bus_timetable(project.id, page=1, per_page=2)
    page_2 = await ProjectService(db).list_bus_timetable(project.id, page=2, per_page=2)

    assert page_1.total == 3
    assert page_1.page == 1
    assert page_1.per_page == 2
    assert [route.route_name for route in page_1.data] == ["A Route", "B Route"]
    assert [route.stops[0].stop_name for route in page_1.data] == ["Stop 1", "Stop 2"]
    assert page_2.total == 3
    assert page_2.page == 2
    assert [route.route_name for route in page_2.data] == ["C Route"]
