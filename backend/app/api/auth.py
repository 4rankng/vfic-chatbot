"""Auth routes: login / refresh / logout / me / change-password.

JWT replaces Supabase Auth. Access tokens are short-lived; refresh tokens are
rotated on each /refresh and rejected if the user has since been disabled/deleted.
/logout bumps the user's token_version, which invalidates both token types at once.
"""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user
from app.identity.application.http import (
    AuthenticatedUser,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    InvalidRefreshTokenError,
    PasswordResetRequestError,
)
from app.identity.infrastructure.http import build_auth_http_service
from app.identity.infrastructure.rate_limits import (
    enforce_auth_forgot_password_rate_limit,
    enforce_auth_login_rate_limit,
    enforce_auth_refresh_rate_limit,
    enforce_auth_reset_password_rate_limit,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordWithOtpRequest,
    TokenResponse,
)
from app.schemas.user import UserOut
from app.shared.domain.errors import BadRequestError, UnauthorizedError
from app.shared.infrastructure.db import get_request_db

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_REFRESH = UnauthorizedError("Invalid refresh token")


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_request_db),
) -> TokenResponse:
    # Argon2 verify is expensive (~50-200ms); cap attempts/IP so a stuffing
    # attack cannot pin the droplet's ASGI workers.
    await enforce_auth_login_rate_limit(request)
    try:
        return await build_auth_http_service(db).login(email=body.email, password=body.password)
    except InvalidCredentialsError as exc:
        raise UnauthorizedError(exc.detail) from exc


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_request_db),
) -> None:
    normalized = body.email.strip().lower()
    await enforce_auth_forgot_password_rate_limit(request, normalized)
    await build_auth_http_service(db).forgot_password(email=normalized)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordWithOtpRequest,
    request: Request,
    db: AsyncSession = Depends(get_request_db),
) -> None:
    normalized = body.email.strip().lower()
    await enforce_auth_reset_password_rate_limit(request, normalized)
    try:
        await build_auth_http_service(db).reset_password(
            email=normalized,
            otp=body.otp,
            new_password=body.new_password,
        )
    except PasswordResetRequestError as exc:
        raise BadRequestError(exc.detail) from exc


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_request_db),
) -> TokenResponse:
    await enforce_auth_refresh_rate_limit(request)
    try:
        return await build_auth_http_service(db).refresh(refresh_token=body.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise _INVALID_REFRESH from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    """Server-side logout: bump the user's token version (SEC-03).

    Clearing localStorage alone left a stolen refresh token usable for its full
    14-day life. The bump invalidates the access token in flight and the refresh
    token together, because both are minted with — and verified against — the
    user's ``token_version``.
    """
    await build_auth_http_service(db).logout(current=current)


@router.get("/me", response_model=UserOut)
async def me(
    current: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> UserOut:
    return await build_auth_http_service(db).me(current=current)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    try:
        await build_auth_http_service(db).change_password(current=current, body=body)
    except InvalidCurrentPasswordError as exc:
        raise BadRequestError(exc.detail) from exc
