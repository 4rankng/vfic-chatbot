"""User CRUD + provisioning (replaces the Supabase vfic_create_user edge function).

Passwords are hashed with argon2; every create/disable/enable/delete is audited.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import Role, User
from app.schemas.user import UserCreate, UserUpdate
from app.services.audit_service import record_audit


class UserProvisioningService:
    """Admin-facing user lifecycle: create / read / update / disable / enable / delete."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def list(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        role: Role | None = None,
    ) -> tuple[list[User], int]:
        base = select(User)
        if role is not None:
            base = base.where(User.role == role)
        total = await self.db.scalar(select(func.count()).select_from(base.subquery()))
        rows = (
            await self.db.scalars(
                base.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
            )
        ).all()
        return list(rows), int(total or 0)

    async def create(self, data: UserCreate, *, actor_id: uuid.UUID | None) -> User:
        user = User(
            email=data.email.strip().lower(),
            password_hash=await hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
            disabled=data.disabled,
        )
        self.db.add(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # users_email_key (lower(email))
            await self.db.rollback()
            raise ValueError(f"user with email already exists: {user.email}") from exc

        await record_audit(
            self.db,
            action="create_user",
            actor_id=actor_id,
            target_type="user",
            target_id=str(user.id),
            payload={
                "email": user.email,
                "role": user.role.value,
                "full_name": user.full_name,
            },
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def _other_enabled_admin_count(self, user_id: uuid.UUID) -> int:
        total = await self.db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == Role.admin, User.disabled.is_(False), User.id != user_id)
        )
        return int(total or 0)

    async def _lock_admin_lifecycle(self) -> None:
        # Serializes role/disabled changes that can remove enabled admins. Without
        # this, two admins can concurrently demote/disable each other after both
        # observe another enabled admin.
        await self.db.execute(select(func.pg_advisory_xact_lock(913_202_406)))

    async def _guard_admin_change(
        self,
        user: User,
        *,
        actor_id: uuid.UUID,
        next_role: Role,
        next_disabled: bool,
    ) -> None:
        await self._lock_admin_lifecycle()
        if user.id == actor_id and user.role == Role.admin:
            if next_disabled:
                raise ValueError("Bạn không thể vô hiệu hóa chính mình")
            if next_role != Role.admin:
                raise ValueError("Bạn không thể tự hạ quyền quản trị của chính mình")

        removes_enabled_admin = (
            user.role == Role.admin
            and not user.disabled
            and (next_role != Role.admin or next_disabled)
        )
        if removes_enabled_admin and await self._other_enabled_admin_count(user.id) == 0:
            raise ValueError("Không thể xóa quản trị viên cuối cùng đang hoạt động")

    async def update(self, user_id: uuid.UUID, data: UserUpdate, *, actor_id: uuid.UUID) -> User:
        user = await self.db.get(User, user_id)
        if user is None:
            raise LookupError("user not found")

        changes = data.model_dump(exclude_unset=True)
        next_role = changes.get("role", user.role)
        next_disabled = changes.get("disabled", user.disabled)
        await self._guard_admin_change(
            user, actor_id=actor_id, next_role=next_role, next_disabled=next_disabled
        )
        security_state_changed = False
        if changes.get("email") is not None:
            next_email = changes["email"].strip().lower()
            # The email is the login identifier and the password-reset target:
            # an admin rewriting it (or an account takeover changing it) must
            # invalidate every token already issued for the old identity (SEC-03).
            security_state_changed = next_email != user.email
            user.email = next_email
        if "full_name" in changes:
            user.full_name = changes["full_name"]
        if changes.get("role") is not None:
            security_state_changed = security_state_changed or user.role != changes["role"]
            user.role = changes["role"]
        if "disabled" in changes:
            security_state_changed = security_state_changed or user.disabled != changes["disabled"]
            user.disabled = changes["disabled"]
        if security_state_changed:
            user.token_version += 1

        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError(f"user with email already exists: {user.email}") from exc

        await record_audit(
            self.db,
            action="update_user",
            actor_id=actor_id,
            target_type="user",
            target_id=str(user.id),
            payload=changes,
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def set_disabled(
        self, user_id: uuid.UUID, disabled: bool, *, actor_id: uuid.UUID
    ) -> User:
        user = await self.db.get(User, user_id)
        if user is None:
            raise LookupError("user not found")

        if user.disabled == disabled:
            return user

        await self._guard_admin_change(
            user, actor_id=actor_id, next_role=user.role, next_disabled=disabled
        )

        user.disabled = disabled
        user.token_version += 1
        await record_audit(
            self.db,
            action="disable_user" if disabled else "enable_user",
            actor_id=actor_id,
            target_type="user",
            target_id=str(user.id),
            payload={"disabled": disabled},
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def reset_password(
        self, user_id: uuid.UUID, new_password: str, *, actor_id: uuid.UUID
    ) -> User:
        """Admin-initiated password set: argon2-hash + revoke all sessions.

        No email / OTP — the new password is applied directly. ``token_version``
        is bumped so every previously-issued JWT for this user is invalidated.
        The plaintext password is never persisted or audited.
        """
        user = await self.db.get(User, user_id)
        if user is None:
            raise LookupError("user not found")
        if user.disabled:
            raise ValueError("Không thể đặt lại mật khẩu cho tài khoản đã vô hiệu hóa")

        user.password_hash = await hash_password(new_password)
        user.token_version += 1  # revoke all existing sessions
        await record_audit(
            self.db,
            action="reset_user_password",
            actor_id=actor_id,
            target_type="user",
            target_id=str(user.id),
            payload={"email": user.email},  # never log the plaintext password
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete(self, user_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
        user = await self.db.get(User, user_id)
        if user is None:
            raise LookupError("user not found")
        if user.id == actor_id:
            raise ValueError("Bạn không thể xóa chính mình")

        await self._guard_admin_change(
            user, actor_id=actor_id, next_role=user.role, next_disabled=True
        )
        await record_audit(
            self.db,
            action="delete_user",
            actor_id=actor_id,
            target_type="user",
            target_id=str(user.id),
            payload={"email": user.email, "role": user.role.value},
        )
        await self.db.delete(user)
        await self.db.commit()
