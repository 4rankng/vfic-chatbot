"""Security changes use the locked current account, not an ORM identity snapshot."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import create_refresh_token, hash_password, verify_password
from app.identity.application.http import InvalidCurrentPasswordError, InvalidRefreshTokenError
from app.identity.infrastructure.http import SqlAlchemyAuthHttpService
from app.models.user import Role, User
from app.models.password_reset import PasswordResetOtp
from app.schemas.auth import ChangePasswordRequest
from app.schemas.user import UserUpdate
from app.services.user_service import UserProvisioningService
from app.services.password_reset_service import PasswordResetError, PasswordResetService, _hash_otp

pytestmark = pytest.mark.integration

ORIGINAL_PASSWORD = "original-test-password"
RESET_PASSWORD = "admin-reset-test-password"
NEW_PASSWORD = "candidate-new-test-password"


async def _users(db):
    target = User(
        id=uuid.uuid4(), email=f"security-{uuid.uuid4().hex}@example.org",
        password_hash=await hash_password(ORIGINAL_PASSWORD), full_name="Security Test",
        role=Role.recruiter, disabled=False, token_version=7,
    )
    admin = User(
        id=uuid.uuid4(), email=f"security-admin-{uuid.uuid4().hex}@example.org",
        password_hash=await hash_password(ORIGINAL_PASSWORD), full_name="Security Admin",
        role=Role.admin, disabled=False, token_version=7,
    )
    db.add_all([target, admin])
    await db.commit()
    return target, admin


async def _challenge(db, target):
    challenge = PasswordResetOtp(
        id=uuid.uuid4(), user_id=target.id, email=target.email,
        otp_hash=_hash_otp(target.email, "123456"), attempt_count=0,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(challenge)
    await db.commit()
    return challenge


async def test_logout_of_a_preloaded_account_revokes_the_latest_token_generation(
    integration_database,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            target, _ = await _users(db)
            target_id = target.id
            async with sessions() as other:
                other_target = await other.get(User, target_id)
                await SqlAlchemyAuthHttpService(other).logout(current=other_target)
            issued_after_first_logout = await create_refresh_token(str(target_id), ver=8)

            await SqlAlchemyAuthHttpService(db).logout(current=target)

            async with sessions() as verifier:
                assert (await verifier.get(User, target_id)).token_version == 9
                with pytest.raises(InvalidRefreshTokenError):
                    await SqlAlchemyAuthHttpService(verifier).refresh(
                        refresh_token=issued_after_first_logout,
                    )
    finally:
        await engine.dispose()


async def test_password_change_revokes_a_generation_issued_after_an_overlapping_logout(
    integration_database,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            target, _ = await _users(db)
            target_id = target.id
            async with sessions() as other:
                other_target = await other.get(User, target_id)
                await SqlAlchemyAuthHttpService(other).logout(current=other_target)
            issued_after_logout = await create_refresh_token(str(target_id), ver=8)

            await SqlAlchemyAuthHttpService(db).change_password(
                current=target,
                body=ChangePasswordRequest(
                    current_password=ORIGINAL_PASSWORD, new_password=NEW_PASSWORD,
                ),
            )

            async with sessions() as verifier:
                saved = await verifier.get(User, target_id)
                assert saved.token_version == 9
                assert await verify_password(NEW_PASSWORD, saved.password_hash)
                with pytest.raises(InvalidRefreshTokenError):
                    await SqlAlchemyAuthHttpService(verifier).refresh(
                        refresh_token=issued_after_logout,
                    )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("presented_password", [ORIGINAL_PASSWORD, RESET_PASSWORD])
async def test_password_change_rechecks_the_hash_replaced_by_an_admin_reset(
    integration_database, presented_password,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            target, admin = await _users(db)
            target_id = target.id
            async with sessions() as other:
                await UserProvisioningService(other).reset_password(
                    target_id, RESET_PASSWORD, actor_id=admin.id,
                )
            change = SqlAlchemyAuthHttpService(db).change_password
            body = ChangePasswordRequest(
                current_password=presented_password, new_password=NEW_PASSWORD,
            )
            if presented_password == ORIGINAL_PASSWORD:
                with pytest.raises(InvalidCurrentPasswordError):
                    await change(current=target, body=body)
                await db.rollback()
            else:
                await change(current=target, body=body)

            async with sessions() as verifier:
                saved = await verifier.get(User, target_id)
                assert saved.token_version == (8 if presented_password == ORIGINAL_PASSWORD else 9)
                expected = RESET_PASSWORD if presented_password == ORIGINAL_PASSWORD else NEW_PASSWORD
                assert await verify_password(expected, saved.password_hash)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("security_change", ["logout", "disable"])
async def test_refresh_rejects_revoked_or_disabled_accounts_even_when_preloaded(
    integration_database, security_change,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            target, admin = await _users(db)
            target_id = target.id
            token = await create_refresh_token(str(target_id), ver=7)
            # Keep this account in the request's identity map before the other
            # transaction commits its security change.
            assert await db.scalar(select(User).where(User.id == target_id)) is target
            async with sessions() as other:
                if security_change == "logout":
                    other_target = await other.get(User, target_id)
                    await SqlAlchemyAuthHttpService(other).logout(current=other_target)
                else:
                    await UserProvisioningService(other).set_disabled(
                        target_id, True, actor_id=admin.id,
                    )

            with pytest.raises(InvalidRefreshTokenError):
                await SqlAlchemyAuthHttpService(db).refresh(refresh_token=token)
    finally:
        await engine.dispose()


async def test_otp_reset_revokes_the_latest_generation_of_a_preloaded_account(
    integration_database,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            target, _ = await _users(db)
            target_id, email = target.id, target.email
            challenge = await _challenge(db, target)
            challenge_id = challenge.id
            async with sessions() as other:
                other_target = await other.get(User, target_id)
                await SqlAlchemyAuthHttpService(other).logout(current=other_target)
            token_after_logout = await create_refresh_token(str(target_id), ver=8)

            await PasswordResetService(db).reset_password(
                email=f"  {email.upper()}  ", otp="123456", new_password=NEW_PASSWORD,
            )

            async with sessions() as verifier:
                saved = await verifier.get(User, target_id)
                assert saved.token_version == 9
                assert await verify_password(NEW_PASSWORD, saved.password_hash)
                assert (await verifier.get(PasswordResetOtp, challenge_id)).consumed_at is not None
                with pytest.raises(InvalidRefreshTokenError):
                    await SqlAlchemyAuthHttpService(verifier).refresh(refresh_token=token_after_logout)
    finally:
        await engine.dispose()


async def test_otp_issued_to_an_old_email_cannot_reset_a_renamed_account(
    integration_database,
):
    engine = create_async_engine(integration_database.async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            target, admin = await _users(db)
            target_id, old_email = target.id, target.email
            challenge = await _challenge(db, target)
            challenge_id = challenge.id
            new_email = f"renamed-{uuid.uuid4().hex}@example.org"
            async with sessions() as other:
                await UserProvisioningService(other).update(
                    target_id, UserUpdate(email=new_email), actor_id=admin.id,
                )

            with pytest.raises(PasswordResetError, match="Mã OTP không hợp lệ hoặc đã hết hạn"):
                await PasswordResetService(db).reset_password(
                    email=old_email, otp="123456", new_password=NEW_PASSWORD,
                )

            async with sessions() as verifier:
                saved = await verifier.get(User, target_id)
                assert saved.email == new_email
                assert saved.token_version == 8
                assert await verify_password(ORIGINAL_PASSWORD, saved.password_hash)
                assert (await verifier.get(PasswordResetOtp, challenge_id)).consumed_at is not None
    finally:
        await engine.dispose()
