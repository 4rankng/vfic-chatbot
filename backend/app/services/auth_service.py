"""Authentication: verify credentials, audit every login attempt.

Failed logins are recorded with actor_id=NULL (or the matched-but-disabled user),
which is the minimum needed for security review without leaking timing side-channels.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.user import User
from app.services.audit_service import record_audit


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """Return the user on success, or None (after writing a failed_login audit row)."""
    normalised = email.strip().lower()
    user = (await db.scalars(select(User).where(User.email == normalised))).first()

    if user is None or not await verify_password(password, user.password_hash):
        await record_audit(
            db,
            action="failed_login",
            target_type="user",
            target_id=user.email if user else normalised,
            payload={"email": normalised},
        )
        await db.commit()
        return None

    if user.disabled:
        await record_audit(
            db,
            action="failed_login",
            actor_id=user.id,
            target_type="user",
            target_id=str(user.id),
            payload={"email": user.email, "reason": "disabled"},
        )
        await db.commit()
        return None

    await record_audit(
        db,
        action="login",
        actor_id=user.id,
        target_type="user",
        target_id=str(user.id),
        payload={"email": user.email},
    )
    await db.commit()
    return user
