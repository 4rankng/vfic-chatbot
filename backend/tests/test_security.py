"""Characterization of the password-hashing + JWT primitives in core.security.

These are the highest-blast-radius primitives in the app — every login and every
token check rides on them — so pin their contract: argon2 hash/verify round-trip
(with per-call salt), JWT issue/decode round-trip with the documented claim
shape, and the failure modes (tampered / malformed / expired -> ValueError) that
callers rely on to turn a bad token into a clean 401 instead of an unhandled 500.
"""

from datetime import timedelta

import pytest

from app.core import security


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
