"""Identity transport rate-limit adapters."""

from fastapi import Request

from app.core.ratelimit import enforce_rate_limit, enforce_rate_limit_key


async def enforce_auth_login_rate_limit(request: Request) -> None:
    await enforce_rate_limit(request, "auth-login", limit=10, window=60)


async def enforce_auth_forgot_password_rate_limit(request: Request, email: str) -> None:
    await enforce_rate_limit(request, "auth-forgot-password", limit=5, window=300)
    await enforce_rate_limit_key("auth-forgot-password-email", email, limit=3, window=900)


async def enforce_auth_reset_password_rate_limit(request: Request, email: str) -> None:
    await enforce_rate_limit(request, "auth-reset-password", limit=10, window=300)
    await enforce_rate_limit_key("auth-reset-password-email", email, limit=10, window=900)


async def enforce_auth_refresh_rate_limit(request: Request) -> None:
    await enforce_rate_limit(request, "auth-refresh", limit=20, window=60)
