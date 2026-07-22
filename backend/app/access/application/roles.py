"""Framework-free role access policies."""

from __future__ import annotations

from app.access.application.ports import PrincipalT
from app.access.domain.policies import assert_admin_role, assert_recruiter_role, role_name


def require_admin_access(principal: PrincipalT) -> PrincipalT:
    assert_admin_role(role_name(principal.role))
    return principal


def require_recruiter_access(principal: PrincipalT) -> PrincipalT:
    assert_recruiter_role(role_name(principal.role))
    return principal
