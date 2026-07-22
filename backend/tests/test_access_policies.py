from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.access.application.installation_access import InstallationAccessPolicy
from app.access.domain.errors import ResourceNotFoundError
from app.api import auth_dependencies, installation_dependencies


class FakeInstallationAuthority:
    def __init__(
        self,
        *,
        active: object | None = None,
        has_state: bool = False,
        require_active_result: object | None = None,
    ) -> None:
        self._active = active
        self._has_state = has_state
        self._require_active_result = require_active_result if require_active_result is not None else active

    async def require_active(self) -> object:
        if self._require_active_result is None:
            raise AssertionError("require_active should not be called in this scenario")
        return self._require_active_result

    async def resolve_active(self) -> object | None:
        return self._active

    async def has_installation_state(self) -> bool:
        return self._has_state


@pytest.mark.asyncio
async def test_installation_access_policy_preserves_legacy_fallback() -> None:
    policy = InstallationAccessPolicy(FakeInstallationAuthority(active=None, has_state=False))

    active = await policy.require_capability_or_legacy("conversation")

    assert active is None


@pytest.mark.asyncio
async def test_installation_access_policy_hides_missing_capability_after_adoption() -> None:
    policy = InstallationAccessPolicy(FakeInstallationAuthority(active=None, has_state=True))

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await policy.require_capability_or_legacy("conversation")

    assert exc_info.value.detail == "not found"


@pytest.mark.asyncio
async def test_installation_access_policy_hides_capability_absence_on_active_installation() -> None:
    active = SimpleNamespace(revision=SimpleNamespace(capability_ids=["knowledge"]))
    policy = InstallationAccessPolicy(FakeInstallationAuthority(active=active))

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await policy.require_capability("conversation")

    assert exc_info.value.detail == "not found"


def test_role_dependencies_preserve_exact_403_details() -> None:
    admin = SimpleNamespace(id=uuid4(), role="admin")
    recruiter = SimpleNamespace(id=uuid4(), role="recruiter")

    assert auth_dependencies.require_admin(admin) is admin
    assert auth_dependencies.require_recruiter(admin) is admin
    assert auth_dependencies.require_recruiter(recruiter) is recruiter

    with pytest.raises(HTTPException) as admin_exc:
        auth_dependencies.require_admin(recruiter)
    assert admin_exc.value.status_code == 403
    assert admin_exc.value.detail == "admin only"

    with pytest.raises(HTTPException) as recruiter_exc:
        auth_dependencies.require_recruiter(SimpleNamespace(id=uuid4(), role="viewer"))
    assert recruiter_exc.value.status_code == 403
    assert recruiter_exc.value.detail == "recruiter only"


@pytest.mark.asyncio
async def test_capability_dependency_maps_not_found_detail(monkeypatch) -> None:
    class MissingCapabilityPolicy:
        async def require_capability(self, capability_id: str) -> object:
            raise ResourceNotFoundError(capability_id and "not found")

    monkeypatch.setattr(
        installation_dependencies,
        "build_installation_access_policy",
        lambda _db: MissingCapabilityPolicy(),
    )
    dependency = installation_dependencies.require_capability("conversation")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(SimpleNamespace(id=uuid4()), SimpleNamespace())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"


@pytest.mark.asyncio
async def test_capability_or_legacy_dependency_maps_not_found_detail(monkeypatch) -> None:
    class MissingCapabilityPolicy:
        async def require_capability_or_legacy(self, capability_id: str) -> object:
            raise ResourceNotFoundError(capability_id and "not found")

    monkeypatch.setattr(
        installation_dependencies,
        "build_installation_access_policy",
        lambda _db: MissingCapabilityPolicy(),
    )
    dependency = installation_dependencies.require_capability_or_legacy("conversation")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(SimpleNamespace(id=uuid4()), SimpleNamespace())

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not found"
