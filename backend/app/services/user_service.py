"""User CRUD + provisioning (replaces the Supabase vfic_create_user edge function).

Passwords are hashed with argon2; every create/disable/enable is audited.
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
    """Admin-facing user lifecycle: create / read / update / disable / enable."""

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
                base.order_by(User.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
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

    async def update(
        self, user_id: uuid.UUID, data: UserUpdate, *, actor_id: uuid.UUID
    ) -> User:
        user = await self.db.get(User, user_id)
        if user is None:
            raise LookupError("user not found")

        changes = data.model_dump(exclude_unset=True)
        if changes.get("email") is not None:
            user.email = changes["email"].strip().lower()
        if "full_name" in changes:
            user.full_name = changes["full_name"]
        if changes.get("role") is not None:
            user.role = changes["role"]
        if "disabled" in changes:
            user.disabled = changes["disabled"]

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

        user.disabled = disabled
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
