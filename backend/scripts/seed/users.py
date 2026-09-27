"""User fixture: the admin and the two recruiters every other domain keys off."""

from __future__ import annotations

from app.core.security import hash_password_sync
from app.models.user import Role, User

from .common import new_uuid


def make_users() -> list[User]:
    pw = hash_password_sync("admin123")
    return [
        User(
            id=new_uuid(),
            email="admin@vfic.dev",
            password_hash=pw,
            full_name="Nguyễn Văn Admin",
            role=Role.admin,
            token_version=0,
            disabled=False,
        ),
        User(
            id=new_uuid(),
            email="lan.nguyen@vfic.dev",
            password_hash=pw,
            full_name="Nguyễn Thị Lan",
            role=Role.recruiter,
            token_version=0,
            disabled=False,
        ),
        User(
            id=new_uuid(),
            email="minh.tran@vfic.dev",
            password_hash=pw,
            full_name="Trần Văn Minh",
            role=Role.recruiter,
            token_version=0,
            disabled=False,
        ),
    ]
