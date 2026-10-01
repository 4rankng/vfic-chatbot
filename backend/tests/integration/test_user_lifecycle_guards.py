"""Account lifecycle policy must use the state serialized by its lock."""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.user import Role, User
from app.schemas.user import UserUpdate
from app.services.user_service import UserProvisioningService

pytestmark = pytest.mark.integration


def _user(*, role: Role, disabled: bool = False) -> User:
    return User(
        id=uuid.uuid4(), email=f"lifecycle-{uuid.uuid4().hex}@example.org",
        password_hash="test-only-unused-hash", full_name="Lifecycle Test",
        role=role, disabled=disabled, token_version=7,
    )


@pytest.mark.parametrize("null_fields", [{"role": None}, {"disabled": None}, {"role": None, "disabled": None, "email": None}])
async def test_nullable_patch_fields_do_not_demote_or_disable_the_admin(
    integration_database, null_fields,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            admin = _user(role=Role.admin)
            db.add(admin)
            await db.commit()
            saved = await UserProvisioningService(db).update(
                admin.id, UserUpdate(**null_fields, full_name=None), actor_id=admin.id,
            )
            assert saved.role == Role.admin
            assert saved.disabled is False
            assert saved.token_version == 7
            assert saved.full_name is None  # This field really is nullable.
    finally:
        await engine.dispose()


@pytest.mark.parametrize("operation", ["disable", "update", "delete"])
async def test_last_admin_guard_refreshes_a_previously_loaded_recruiter(
    integration_database, operation,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            actor = _user(role=Role.admin)
            target = _user(role=Role.recruiter)
            target_id = target.id
            db.add_all([actor, target])
            await db.commit()
            # This request has already read the target. Another lifecycle
            # transaction promotes it and leaves it as the sole enabled admin.
            cached = await db.get(User, target.id)
            assert cached.role == Role.recruiter
            async with sessions() as other:
                await other.execute(update(User).values(disabled=True))
                await other.execute(update(User).where(User.id == target.id).values(role=Role.admin, disabled=False))
                await other.commit()
            service = UserProvisioningService(db)
            with pytest.raises(ValueError, match="quản trị viên cuối cùng"):
                if operation == "disable":
                    await service.set_disabled(target.id, True, actor_id=actor.id)
                elif operation == "update":
                    await service.update(target.id, UserUpdate(disabled=True), actor_id=actor.id)
                else:
                    await service.delete(target.id, actor_id=actor.id)
            await db.rollback()
            fresh = await db.get(User, target_id)
            assert fresh is not None and fresh.role == Role.admin and not fresh.disabled
    finally:
        await engine.dispose()


async def test_duplicate_email_update_keeps_the_expected_conflict_after_rollback(
    integration_database,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            actor = _user(role=Role.admin)
            target = _user(role=Role.recruiter)
            original_email, target_id = target.email, target.id
            db.add_all([actor, target])
            await db.commit()
            with pytest.raises(ValueError, match="email already exists"):
                await UserProvisioningService(db).update(
                    target_id, UserUpdate(email=actor.email), actor_id=actor.id,
                )
            assert (await db.get(User, target_id)).email == original_email
    finally:
        await engine.dispose()


async def test_password_reset_revokes_the_latest_session_generation(
    integration_database, monkeypatch,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.services.user_service.hash_password", AsyncMock(return_value="test-only-new-hash"))
    try:
        async with sessions() as db:
            target = _user(role=Role.recruiter)
            actor = _user(role=Role.admin)
            target_id, actor_id = target.id, actor.id
            db.add_all([target, actor])
            await db.commit()
            # Another security change invalidated generation 7 while this
            # session still retains the old ORM snapshot.
            async with sessions() as other:
                await other.execute(update(User).where(User.id == target_id).values(token_version=8))
                await other.commit()
            saved = await UserProvisioningService(db).reset_password(
                target_id, "test-only-password", actor_id=actor_id,
            )
            assert saved.token_version == 9
    finally:
        await engine.dispose()
