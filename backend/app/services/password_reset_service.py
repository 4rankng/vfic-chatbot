"""Password reset OTP lifecycle."""

import asyncio
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.password_reset import PasswordResetOtp
from app.models.user import User
from app.services.audit_service import record_audit
from app.services.email_service import send_password_reset_otp

logger = logging.getLogger(__name__)


class PasswordResetError(ValueError):
    """Raised for invalid, expired, consumed, or over-attempted OTPs."""


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_otp(email: str, otp: str) -> str:
    settings = get_settings()
    message = f"{_normalize_email(email)}:{otp}".encode("utf-8")
    return hmac.digest(settings.jwt_secret.encode("utf-8"), message, "sha256").hex()


def _new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


class PasswordResetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    async def request_reset(self, email: str) -> None:
        normalized = _normalize_email(email)
        user = (
            await self.db.scalars(select(User).where(func.lower(User.email) == normalized))
        ).first()
        if user is None or user.disabled:
            await record_audit(
                self.db,
                action="password_reset_requested",
                target_type="user",
                target_id=normalized,
                payload={"eligible": False},
            )
            await self.db.commit()
            return

        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(PasswordResetOtp)
            .where(
                PasswordResetOtp.user_id == user.id,
                PasswordResetOtp.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        otp = _new_otp()
        reset = PasswordResetOtp(
            user_id=user.id,
            email=normalized,
            otp_hash=_hash_otp(normalized, otp),
            expires_at=now + timedelta(minutes=self.settings.password_reset_otp_ttl_minutes),
        )
        self.db.add(reset)
        await record_audit(
            self.db,
            action="password_reset_requested",
            actor_id=user.id,
            target_type="user",
            target_id=str(user.id),
            payload={"email": normalized},
        )
        await self.db.commit()
        asyncio.create_task(self._send_reset_email(user_id=user.id, email=normalized, otp=otp))

    async def _send_reset_email(self, *, user_id: uuid.UUID, email: str, otp: str) -> None:
        from app.core.db import async_session

        try:
            provider_id = await send_password_reset_otp(to_email=email, otp=otp)
        except Exception:  # noqa: BLE001 - provider/network failure must not leak to caller
            logger.exception("password reset email delivery failed user_id=%s", user_id)
            async with async_session() as db:
                await record_audit(
                    db,
                    action="password_reset_email_failed",
                    actor_id=user_id,
                    target_type="user",
                    target_id=str(user_id),
                    payload={"email": email},
                )
                await db.commit()
            return

        if provider_id:
            async with async_session() as db:
                await record_audit(
                    db,
                    action="password_reset_email_sent",
                    actor_id=user_id,
                    target_type="user",
                    target_id=str(user_id),
                    payload={"email": email, "provider_id": provider_id},
                )
                await db.commit()

    async def reset_password(self, *, email: str, otp: str, new_password: str) -> None:
        normalized = _normalize_email(email)
        now = datetime.now(timezone.utc)
        reset = (
            await self.db.scalars(
                select(PasswordResetOtp)
                .where(
                    func.lower(PasswordResetOtp.email) == normalized,
                    PasswordResetOtp.consumed_at.is_(None),
                )
                .order_by(PasswordResetOtp.created_at.desc())
                .with_for_update()
            )
        ).first()
        if reset is None:
            raise PasswordResetError("Mã OTP không hợp lệ hoặc đã hết hạn")

        if reset.expires_at <= now:
            reset.consumed_at = now
            await self.db.commit()
            raise PasswordResetError("Mã OTP không hợp lệ hoặc đã hết hạn")

        if reset.attempt_count >= self.settings.password_reset_otp_attempt_limit:
            reset.consumed_at = now
            await self.db.commit()
            raise PasswordResetError("Mã OTP không hợp lệ hoặc đã hết hạn")

        expected = reset.otp_hash
        candidate = _hash_otp(normalized, otp)
        if not hmac.compare_digest(expected, candidate):
            reset.attempt_count += 1
            if reset.attempt_count >= self.settings.password_reset_otp_attempt_limit:
                reset.consumed_at = now
            await self.db.commit()
            raise PasswordResetError("Mã OTP không hợp lệ hoặc đã hết hạn")

        user = await self.db.get(User, reset.user_id, with_for_update=True)
        if user is None or user.disabled:
            reset.consumed_at = now
            await self.db.commit()
            raise PasswordResetError("Mã OTP không hợp lệ hoặc đã hết hạn")

        user.password_hash = await hash_password(new_password)
        user.token_version += 1
        reset.consumed_at = now
        await record_audit(
            self.db,
            action="password_reset_completed",
            actor_id=user.id,
            target_type="user",
            target_id=str(user.id),
            payload={"email": normalized},
        )
        await self.db.commit()
