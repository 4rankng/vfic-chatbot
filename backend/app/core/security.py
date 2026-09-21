"""Password hashing (argon2) + JWT issue/verify.

passlib argon2 (hash/verify) and PyJWT (encode/decode) are CPU-bound,
blocking calls. Running them inline inside async handlers/dependencies stalls the
single event loop — concurrent logins (~50-200ms of argon2 each) would freeze every
in-flight webhook and SSE stream. The public functions below are therefore
**async** and run the crypto on a worker thread via ``asyncio.to_thread``.

Sync ``*_sync`` helpers exist for the handful of genuinely synchronous callers
(the create_admin / migrate_from_supabase scripts). The async app must NEVER call
the ``_sync`` variants from an ``async def``.

PyJWT replaced python-jose as the JWT library: python-jose 3.5.0 still pulls
``ecdsa``, which is affected by the Minerva timing attack on P-256
(CVE-2024-23342) and has no upstream fix. PyJWT uses ``cryptography`` for
HS256/RS256/ES256/EdDSA and does not transitively depend on ``ecdsa``.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TypedDict

import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")
_settings = get_settings()


class TokenPayload(TypedDict):
    """The JWT claims this app issues and reads back (see ``_encode``).

    Only the claims the auth layer actually reads are declared — ``iat``/``exp``
    travel in the token too but are not accessed, so they stay runtime-only to
    avoid pinning PyJWT's decoded timestamp type.
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
    """Decode + verify a JWT synchronously. Raises ValueError on any PyJWT failure."""
    try:
        payload = jwt.decode(
            token,
            _settings.jwt_secret,
            algorithms=[_settings.jwt_algorithm],
        )
    except InvalidTokenError as exc:
        raise ValueError("invalid or expired token") from exc
    return _payload_from_dict(payload)


def _payload_from_dict(payload: dict) -> TokenPayload:
    return TokenPayload(
        sub=str(payload["sub"]),
        type=str(payload["type"]),
        ver=int(payload["ver"]),
    )


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
        return jwt.encode(
            payload,
            _settings.jwt_secret,
            algorithm=_settings.jwt_algorithm,
        )

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

    PyJWT raises its own ``InvalidTokenError`` hierarchy on expired / tampered /
    malformed tokens — none of which are ``ValueError`` / ``KeyError``.
    Translate to ``ValueError`` so every caller's existing
    ``except (ValueError, KeyError)`` turns a bad token into a clean 401
    instead of an unhandled 500 with a stacktrace.
    """
    return await asyncio.to_thread(decode_token_sync, token)