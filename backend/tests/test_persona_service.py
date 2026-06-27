"""Phase 3 characterization tests for PersonaService (direct service-level).

Locks the behavior moved out of the personas router: ORM-based activate (deactivates
other globals + audits), project-scoped activation rejection, and create+list.
"""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.company import Project
from app.models.persona import Persona
from app.models.user import User
from app.schemas.personas import PersonaCreate
from app.services.persona_service import PersonaService
from tests.conftest import ADMIN_EMAIL

pytestmark = pytest.mark.asyncio


async def _admin(db_session) -> User:
    return (await db_session.scalars(select(User).where(User.email == ADMIN_EMAIL))).first()


async def test_activate_deactivates_other_globals_and_audits(db_session, seed):
    db = db_session
    svc = PersonaService(db)
    a = Persona(name="A", slug=f"a-{uuid.uuid4().hex[:4]}", body_md="x", is_active=False)
    b = Persona(name="B", slug=f"b-{uuid.uuid4().hex[:4]}", body_md="y", is_active=False)
    db.add_all([a, b])
    await db.commit()
    await db.refresh(a)
    await db.refresh(b)

    await svc.activate(a.id)
    await svc.activate(b.id)  # ORM update deactivates a

    await db.refresh(a)
    await db.refresh(b)
    assert b.is_active is True
    assert a.is_active is False  # deactivated by the activate(other) ORM update
    audits = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "activate_persona"))
    ).all()
    assert len(audits) >= 2


async def test_activate_rejects_project_scoped_persona(db_session, seed):
    db = db_session
    proj = Project(slug=f"p-{uuid.uuid4().hex[:4]}", name="P", is_active=True)
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    p = Persona(
        name="scoped", slug=f"s-{uuid.uuid4().hex[:4]}", body_md="x", project_id=proj.id
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)

    with pytest.raises(HTTPException) as exc:
        await PersonaService(db).activate(p.id)
    assert exc.value.status_code == 400


async def test_create_then_list(db_session, seed):
    db = db_session
    admin = await _admin(db)
    svc = PersonaService(db)
    created = await svc.create(
        PersonaCreate(name="New", slug=f"n-{uuid.uuid4().hex[:4]}", body_md="hello"), admin
    )
    assert created.id is not None
    rows = await svc.list()
    assert any(r.id == created.id for r in rows)
