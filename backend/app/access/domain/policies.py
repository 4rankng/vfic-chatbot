"""Role policy helpers for the single-tenant installation."""

from __future__ import annotations

from app.access.domain.errors import AccessDeniedError

ADMIN_ROLE = "admin"
RECRUITER_ROLE = "recruiter"


def role_name(role: object) -> str:
    if isinstance(role, str):
        return role
    value = getattr(role, "value", None)
    return value if isinstance(value, str) else ""


def assert_admin_role(role: str) -> None:
    if role != ADMIN_ROLE:
        raise AccessDeniedError("admin only")


def assert_recruiter_role(role: str) -> None:
    if role not in {ADMIN_ROLE, RECRUITER_ROLE}:
        raise AccessDeniedError("recruiter only")
