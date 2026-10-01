"""SEC-03: server-side logout, stale-refresh rejection, and email-change revocation.

Both token types carry ``ver`` and both verifiers compare it to
``users.token_version``. Logout and security changes revoke the current
generation; refresh remains valid for that generation until it is revoked.
These tests pin logout, password-change, and email-change revocation end to end.

Pure unit tests: a recording fake session stands in for the DB, and the real
JWT primitives + real Argon2 hashing run, so the token/session semantics under
test are production code.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api.auth_dependencies import get_current_user
from app.core.errors import register_domain_exception_handlers
from app.core.security import hash_password
from app.identity.application.http import InvalidCurrentPasswordError, InvalidRefreshTokenError
from app.identity.domain.errors import AuthenticationError
from app.identity.domain.role import Role
from app.identity.infrastructure.authentication import build_access_token_authenticator
from app.identity.infrastructure.http import SqlAlchemyAuthHttpService
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest
from app.schemas.user import UserUpdate
from app.services.user_service import UserProvisioningService
from app.shared.infrastructure.db import get_request_db

PASSWORD = "correct-horse-battery"


class _ScalarsResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value


class _FakeSession:
    """Minimal AsyncSession double: enough for auth + user provisioning."""

    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.audit_actions: list[str] = []
        self.commits = 0

    async def get(self, model, primary_key, **_options):  # noqa: ANN001
        if self.user is not None and self.user.id == primary_key:
            return self.user
        return None

    async def scalars(self, _statement):  # noqa: ANN001
        return _ScalarsResult(self.user)

    async def scalar(self, _statement):  # noqa: ANN001
        return 0

    async def execute(self, _statement):  # noqa: ANN001
        return None

    def add(self, instance) -> None:  # noqa: ANN001
        action = getattr(instance, "action", None)
        if isinstance(action, str):
            self.audit_actions.append(action)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _instance, **_options) -> None:  # noqa: ANN001
        return None


async def _user(*, email: str = "recruiter@example.com", role: Role = Role.recruiter) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash=await hash_password(PASSWORD),
        full_name="Recruiter",
        role=role,
        disabled=False,
        token_version=0,
    )


@pytest.mark.asyncio
async def test_logout_revokes_both_token_types_and_a_fresh_login_still_works() -> None:
    user = await _user()
    db = _FakeSession(user)
    service = SqlAlchemyAuthHttpService(db)
    access_authenticator = build_access_token_authenticator(db)

    issued = await service.login(email=user.email, password=PASSWORD)
    # Pre-logout refresh issues a pair and the access token authenticates.
    await service.refresh(refresh_token=issued.refresh_token)
    assert (await access_authenticator.authenticate(issued.access_token)).id == user.id

    await service.logout(current=user)

    assert user.token_version == 1
    assert "logout" in db.audit_actions
    assert db.commits == 2  # login's audit commit + logout's commit

    # The token pair minted before the logout is dead — including the refresh
    # token, which is the whole point of SEC-03.
    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(refresh_token=issued.refresh_token)
    with pytest.raises(AuthenticationError):
        await access_authenticator.authenticate(issued.access_token)

    # A fresh login mints tokens at the new generation and works again.
    fresh = await service.login(email=user.email, password=PASSWORD)
    refreshed = await service.refresh(refresh_token=fresh.refresh_token)
    assert refreshed.access_token
    assert (await access_authenticator.authenticate(refreshed.access_token)).id == user.id


@pytest.mark.asyncio
async def test_repeated_logout_keeps_revoking() -> None:
    user = await _user()
    service = SqlAlchemyAuthHttpService(_FakeSession(user))

    await service.logout(current=user)
    await service.logout(current=user)

    assert user.token_version == 2


async def test_password_change_revokes_old_tokens_and_preserves_audit() -> None:
    user = await _user()
    db = _FakeSession(user)
    service = SqlAlchemyAuthHttpService(db)
    issued = await service.login(email=user.email, password=PASSWORD)

    await service.change_password(
        current=user,
        body=ChangePasswordRequest(current_password=PASSWORD, new_password="new-test-password"),
    )

    assert user.token_version == 1
    assert db.audit_actions == ["login", "change_password"]
    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(refresh_token=issued.refresh_token)
    assert await service.login(email=user.email, password="new-test-password")


async def test_wrong_current_password_does_not_change_security_state_or_audit() -> None:
    user = await _user()
    db = _FakeSession(user)
    original_hash = user.password_hash
    with pytest.raises(InvalidCurrentPasswordError):
        await SqlAlchemyAuthHttpService(db).change_password(
            current=user,
            body=ChangePasswordRequest(current_password="wrong", new_password="new-test-password"),
        )
    assert user.password_hash == original_hash
    assert user.token_version == 0
    assert db.audit_actions == []
    assert db.commits == 0


def _auth_app(user: User, db: _FakeSession) -> FastAPI:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(auth_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_request_db] = lambda: db
    return app


def _logout_client(user: User, db: _FakeSession) -> TestClient:
    return TestClient(_auth_app(user, db))


@pytest.mark.asyncio
async def test_refresh_route_rejects_a_token_minted_before_logout() -> None:
    """The consumer-visible contract: 200 -> 204 -> 401 on the real routes."""
    user = await _user()
    db = _FakeSession(user)
    issued = await SqlAlchemyAuthHttpService(db).login(email=user.email, password=PASSWORD)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_auth_app(user, db)), base_url="http://test"
    ) as client:
        before = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": issued.refresh_token}
        )
        logged_out = await client.post("/api/v1/auth/logout")
        after = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": issued.refresh_token}
        )

    assert before.status_code == 200
    assert logged_out.status_code == 204
    assert after.status_code == 401


def test_logout_route_bumps_the_token_version() -> None:
    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash="x",
        role=Role.admin,
        disabled=False,
        token_version=4,
    )
    db = _FakeSession(user)

    response = _logout_client(user, db).post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert user.token_version == 5
    assert db.audit_actions == ["logout"]


def test_logout_route_requires_an_authenticated_caller() -> None:
    app = FastAPI()
    register_domain_exception_handlers(app)
    app.include_router(auth_api.router, prefix="/api/v1")

    # No Authorization header and no dependency override -> the real bearer
    # dependency rejects before the service (and the DB) is reached.
    assert TestClient(app).post("/api/v1/auth/logout").status_code == 401


@pytest.mark.asyncio
async def test_changing_the_email_revokes_existing_tokens() -> None:
    user = await _user()
    db = _FakeSession(user)

    updated = await UserProvisioningService(db).update(
        user.id,
        UserUpdate(email="Moved@Example.com"),
        actor_id=uuid.uuid4(),
    )

    assert updated.email == "moved@example.com"
    assert updated.token_version == 1


@pytest.mark.asyncio
async def test_non_security_updates_do_not_revoke_tokens() -> None:
    user = await _user()
    db = _FakeSession(user)

    updated = await UserProvisioningService(db).update(
        user.id,
        UserUpdate(full_name="New Name"),
        actor_id=uuid.uuid4(),
    )

    assert updated.full_name == "New Name"
    assert updated.token_version == 0


@pytest.mark.asyncio
async def test_email_and_role_change_together_revoke_exactly_once() -> None:
    user = await _user()
    db = _FakeSession(user)

    updated = await UserProvisioningService(db).update(
        user.id,
        UserUpdate(email="promoted@example.com", role=Role.admin),
        actor_id=uuid.uuid4(),
    )

    assert updated.token_version == 1
