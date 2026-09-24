"""Characterization of the password-hashing + JWT primitives in core.security.

These are the highest-blast-radius primitives in the app — every login and every
token check rides on them — so pin their contract: argon2 hash/verify round-trip
(with per-call salt), JWT issue/decode round-trip with the documented claim
shape, the issuer/audience/required-claim enforcement added by SEC-08, and the
failure modes (tampered / malformed / expired / missing-claim -> ValueError) that
callers rely on to turn a bad token into a clean 401 instead of an unhandled 500.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import ValidationError

from app.core import security
from app.core.config import Settings, get_settings


# --- argon2 hash/verify ------------------------------------------------------


def test_hash_verify_round_trip_and_rejects_wrong_password():
    hashed = security.hash_password_sync("correct horse battery staple")
    assert hashed.startswith("$argon2")
    assert security.verify_password_sync("correct horse battery staple", hashed) is True
    assert security.verify_password_sync("a-wrong-guess", hashed) is False


def test_hash_uses_a_random_salt_per_call():
    a = security.hash_password_sync("same-password")
    b = security.hash_password_sync("same-password")
    # Same input, different output -> argon2 is salting each hash.
    assert a != b
    assert security.verify_password_sync("same-password", a)
    assert security.verify_password_sync("same-password", b)


@pytest.mark.asyncio
async def test_async_hash_and_verify_match_sync_semantics():
    hashed = await security.hash_password("pw")
    assert await security.verify_password("pw", hashed) is True
    assert await security.verify_password("nope", hashed) is False


# --- JWT issue/decode --------------------------------------------------------


@pytest.mark.asyncio
async def test_access_token_round_trips_claims():
    token = await security.create_access_token("user-123", ver=3)
    payload = await security.decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"
    assert payload["ver"] == 3


@pytest.mark.asyncio
async def test_refresh_token_carries_refresh_type():
    token = await security.create_refresh_token("user-9", ver=0)
    payload = await security.decode_token(token)
    assert payload["type"] == "refresh"
    assert payload["sub"] == "user-9"


@pytest.mark.asyncio
async def test_decode_rejects_tampered_token():
    token = await security.create_access_token("user-1")
    # Perturb the tail (signature) so verification fails.
    tail = "AA" if not token.endswith("AA") else "BB"
    tampered = token[: -len(tail)] + tail
    with pytest.raises(ValueError):
        await security.decode_token(tampered)


def test_decode_rejects_malformed_token():
    with pytest.raises(ValueError):
        security.decode_token_sync("not.a.jwt")


@pytest.mark.asyncio
async def test_decode_rejects_expired_token():
    # Sign via the real encoder with a negative expiry so exp is already in the
    # past; jose must reject it and the wrapper must surface that as ValueError.
    token = await security._encode("user-1", timedelta(hours=-1), "access", ver=0)
    with pytest.raises(ValueError):
        await security.decode_token(token)


# --- SEC-08: issuer / audience / required claims -----------------------------


def _mint(**overrides) -> str:
    """Sign a token with the real secret, overriding individual claims."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "user-1",
        "type": "access",
        "ver": 0,
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    payload.update(overrides)
    for claim, value in list(overrides.items()):
        if value is None:
            payload.pop(claim, None)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_issued_tokens_carry_issuer_and_audience():
    settings = get_settings()
    for token in (
        await security.create_access_token("user-1"),
        await security.create_refresh_token("user-1"),
    ):
        claims = jwt.decode(token, options={"verify_signature": False})
        assert claims["iss"] == settings.jwt_issuer
        assert claims["aud"] == settings.jwt_audience


@pytest.mark.asyncio
async def test_decode_accepts_a_token_minted_with_the_configured_issuer_and_audience():
    assert (await security.decode_token(_mint()))["sub"] == "user-1"


@pytest.mark.parametrize(
    "claim",
    ["iss", "aud", "exp", "sub", "type", "ver"],
)
@pytest.mark.asyncio
async def test_decode_rejects_a_token_missing_a_required_claim(claim):
    with pytest.raises(ValueError):
        await security.decode_token(_mint(**{claim: None}))


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "some-other-service"),
        ("aud", "some-other-service"),
        ("aud", ["some-other-service"]),
    ],
)
@pytest.mark.asyncio
async def test_decode_rejects_a_foreign_issuer_or_audience(claim, value):
    # Same secret, wrong trust boundary: a token minted for a sibling service
    # must not be interchangeable here.
    with pytest.raises(ValueError):
        await security.decode_token(_mint(**{claim: value}))


def test_jwt_algorithm_is_allowlisted_and_normalized():
    assert Settings(app_env="development", jwt_algorithm="hs256").jwt_algorithm == "HS256"
    assert Settings(app_env="development", jwt_algorithm=" HS512 ").jwt_algorithm == "HS512"


@pytest.mark.parametrize("algorithm", ["RS256", "none", "HS256,RS256", "", "ES256"])
def test_a_bad_jwt_algorithm_refuses_to_boot(algorithm):
    with pytest.raises(ValidationError):
        Settings(app_env="development", jwt_algorithm=algorithm)


def test_a_bad_jwt_algorithm_env_value_fails_the_settings_load(monkeypatch):
    # The boot path: main.py calls get_settings() at import, so a bad env value
    # must raise there rather than turn every login into a request-time 500.
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()
