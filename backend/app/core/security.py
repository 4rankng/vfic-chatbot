"""Password hashing (argon2) + JWT issue/verify (replaces Supabase Auth).

passlib argon2 (hash/verify) and jose jwt (encode/decode) are CPU-bound,
blocking calls. Running them inline inside async handlers/dependencies stalls the
single event loop — concurrent logins (~50-200ms of argon2 each) would freeze every
in-flight webhook and SSE stream. The public functions below are therefore
**async** and run the crypto on a worker thread via ``asyncio.to_thread``.

Sync ``*_sync`` helpers exist for the handful of genuinely synchronous callers
(the create_admin / migrate_from_supabase scripts). The async app must NEVER call
the ``_sync`` variants from an ``async def``.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from jose import jwt
from jose.exceptions import JWTError
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")
_settings = get_settings()


class TokenPayload(TypedDict):
    """The JWT claims this app issues and reads back (see ``_encode``).

    Only the claims the auth layer actually reads are declared — ``iat``/``exp``
    travel in the token too but are not accessed, so they stay runtime-only to
    avoid pinning jose's decoded timestamp type.
    """

    sub: str
    type: str  # "access" | "refresh"
    ver: int


# --- sync primitives (scripts only; never call from an async def) ---
def hash_password_sync(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password_sync(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def decode_token_sync(token: str) -> TokenPayload:
    """Decode + verify a JWT synchronously. Raises ValueError on any jose failure."""
    try:
        return jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("invalid or expired token") from exc


# --- async wrappers (the async app uses these to avoid blocking the loop) ---
async def hash_password(plain: str) -> str:
    return await asyncio.to_thread(hash_password_sync, plain)


async def verify_password(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password_sync, plain, hashed)


async def _encode(subject: str, expires_in: timedelta, token_type: str, *, ver: int) -> str:
    def _sign() -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": subject,
            "type": token_type,
            "ver": ver,
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)

    return await asyncio.to_thread(_sign)


async def create_access_token(subject: str, *, ver: int = 0) -> str:
    return await _encode(
        subject, timedelta(minutes=_settings.access_token_expire_minutes), "access", ver=ver
    )


async def create_refresh_token(subject: str, *, ver: int = 0) -> str:
    return await _encode(
        subject, timedelta(days=_settings.refresh_token_expire_days), "refresh", ver=ver
    )


async def decode_token(token: str) -> TokenPayload:
    """Decode + verify a JWT off the event loop.

    jose raises its own ``JWTError`` hierarchy (``ExpiredSignatureError``,
    ``JWTClaimsError``, ...) on expired/tampered/malformed tokens — none of which
    are ``ValueError``/``KeyError``. Translate to ``ValueError`` so every caller's
    existing ``except (ValueError, KeyError)`` turns a bad token into a clean 401
    instead of an unhandled 500 with a stacktrace.
    """
    return await asyncio.to_thread(decode_token_sync, token)
