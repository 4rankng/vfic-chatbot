"""Unit tests for admin-initiated password reset in UserProvisioningService.

Pure unit tests — no live DB. ``AsyncSession`` is faked so we can assert which
methods were called, with which args, and that the plaintext password never
reaches the audit log or persistence in cleartext.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models.user import Role, User
from app.services.user_service import UserProvisioningService


def _make_user(*, disabled: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        email="recruit@example.com",
        password_hash="$argon2id$old",
        full_name="Recruiter One",
        role=Role.recruiter,
        disabled=disabled,
        token_version=0,
    )


class _FakeSession:
    """Minimal AsyncSession double: only what reset_password touches."""

    def __init__(self, user: User | None) -> None:
        self._user = user
        self.added: list = []
        self.committed = False
        self.refreshed = False

    async def get(self, _model, _pk):
        return self._user

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        self.refreshed = True


@pytest.mark.asyncio
async def test_reset_password_hashes_and_revokes_sessions():
    user = _make_user()
    session = _FakeSession(user)
    actor = uuid.uuid4()
    svc = UserProvisioningService(session)  # type: ignore[arg-type]

    with (
        patch(
            "app.services.user_service.hash_password",
            new=AsyncMock(return_value="$argon2id$new"),
        ) as mock_hash,
        patch(
            "app.services.user_service.record_audit",
            new=AsyncMock(),
        ) as mock_audit,
    ):
        result = await svc.reset_password(user.id, "supersecret", actor_id=actor)

    assert result is user
    assert user.password_hash == "$argon2id$new"
    assert user.token_version == 1  # bumped → existing JWTs rejected
    mock_hash.assert_awaited_once_with("supersecret")
    # audit action + target id; plaintext password must NOT appear in payload
    mock_audit.assert_awaited_once()
    _args, kwargs = mock_audit.call_args
    assert kwargs["action"] == "reset_user_password"
    assert kwargs["target_id"] == str(user.id)
    assert kwargs["actor_id"] == actor
    assert kwargs["payload"] == {"email": user.email}
    assert "supersecret" not in str(kwargs["payload"])
    assert session.committed
    assert session.refreshed


@pytest.mark.asyncio
async def test_reset_password_missing_user_raises_lookup_error():
    session = _FakeSession(None)
    svc = UserProvisioningService(session)  # type: ignore[arg-type]

    with pytest.raises(LookupError):
        await svc.reset_password(uuid.uuid4(), "supersecret", actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_reset_password_disabled_user_raises_value_error():
    user = _make_user(disabled=True)
    session = _FakeSession(user)
    svc = UserProvisioningService(session)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        await svc.reset_password(user.id, "supersecret", actor_id=uuid.uuid4())
