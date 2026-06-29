"""Auth routes: login / refresh / me / change-password.

JWT replaces Supabase Auth. Access tokens are short-lived; refresh tokens are
rotated on each /refresh and rejected if the user has since been disabled/deleted.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import enforce_rate_limit, enforce_rate_limit_key
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordWithOtpRequest,
    TokenResponse,
)
from app.schemas.user import UserOut
from app.services.audit_service import record_audit
from app.services.auth_service import authenticate
from app.services.password_reset_service import PasswordResetError, PasswordResetService

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = get_settings()

_INVALID_REFRESH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
)


async def _tokens_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=await create_access_token(str(user.id), ver=user.token_version),
        refresh_token=await create_refresh_token(str(user.id), ver=user.token_version),
        token_type="bearer",
        expires_in=_settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    # Argon2 verify is expensive (~50-200ms); cap attempts/IP so a stuffing
    # attack cannot pin the droplet's ASGI workers.
    await enforce_rate_limit(request, "auth-login", limit=10, window=60)
    user = await authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng",
        )
    return await _tokens_for(user)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    normalized = body.email.strip().lower()
    await enforce_rate_limit(request, "auth-forgot-password", limit=5, window=300)
    await enforce_rate_limit_key(
        "auth-forgot-password-email", normalized, limit=3, window=900
    )
    await PasswordResetService(db).request_reset(normalized)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordWithOtpRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    normalized = body.email.strip().lower()
    await enforce_rate_limit(request, "auth-reset-password", limit=10, window=300)
    await enforce_rate_limit_key("auth-reset-password-email", normalized, limit=10, window=900)
    try:
        await PasswordResetService(db).reset_password(
            email=normalized, otp=body.otp, new_password=body.new_password
        )
    except PasswordResetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    await enforce_rate_limit(request, "auth-refresh", limit=20, window=60)
    try:
        payload = await decode_token(body.refresh_token)
    except Exception:
        raise _INVALID_REFRESH
    if payload.get("type") != "refresh":
        raise _INVALID_REFRESH
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _INVALID_REFRESH

    # Re-check liveness so a disabled/deleted user cannot mint new tokens.
    user = await db.get(User, user_id)
    if user is None or user.disabled:
        raise _INVALID_REFRESH
    # Reject refresh tokens superseded by a password change (ver mismatch).
    if payload.get("ver", 0) != user.token_version:
        raise _INVALID_REFRESH
    return await _tokens_for(user)


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)) -> User:
    return current


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not await verify_password(body.current_password, current.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mật khẩu hiện tại không đúng",
        )
    current.password_hash = await hash_password(body.new_password)
    # Bump token_version so every previously-issued access/refresh token (carrying
    # the old `ver`) is rejected at the auth gate — the old session is revoked.
    current.token_version += 1
    await record_audit(
        db,
        action="change_password",
        actor_id=current.id,
        target_type="user",
        target_id=str(current.id),
    )
    await db.commit()
