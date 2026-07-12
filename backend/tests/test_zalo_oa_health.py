"""Signature-health recorder — hermetic via a fake async redis (no real Redis)."""

from __future__ import annotations

import pytest

from app.services import zalo_oa_health


class _FakeRedis:
    """Minimal async redis subset: hset(mapping=), hincrby, expire, hgetall."""

    def __init__(self) -> None:
        self._h: dict[str, str] = {}

    async def hset(self, _key, mapping=None, **fields):
        self._h.update(mapping or fields)

    async def hincrby(self, _key, field, amount):
        cur = int(self._h.get(field, 0)) + amount
        self._h[field] = str(cur)
        return cur

    async def expire(self, _key, _ttl):
        return True

    async def hgetall(self, _key):
        return dict(self._h)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(zalo_oa_health, "get_redis", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_record_success_marks_verified_and_resets_failures(fake_redis):
    await zalo_oa_health.record_oa_signature(ok=True)
    health = await zalo_oa_health.read_oa_signature_health()
    assert health["last_status"] == "verified"
    assert health["consec_failures"] == 0
    assert health["last_ts"] is not None
    assert health["last_mismatch_ts"] is None


@pytest.mark.asyncio
async def test_record_mismatch_counts_consecutive_failures(fake_redis):
    await zalo_oa_health.record_oa_signature(ok=False)
    await zalo_oa_health.record_oa_signature(ok=False)
    health = await zalo_oa_health.read_oa_signature_health()
    assert health["last_status"] == "mismatched"
    assert health["consec_failures"] == 2
    assert health["last_mismatch_ts"] is not None


@pytest.mark.asyncio
async def test_success_after_mismatch_resets_failure_count(fake_redis):
    await zalo_oa_health.record_oa_signature(ok=False)
    await zalo_oa_health.record_oa_signature(ok=False)
    await zalo_oa_health.record_oa_signature(ok=True)
    health = await zalo_oa_health.read_oa_signature_health()
    assert health["last_status"] == "verified"
    assert health["consec_failures"] == 0


@pytest.mark.asyncio
async def test_record_never_raises_when_redis_fails(monkeypatch):
    monkeypatch.setattr(
        zalo_oa_health, "get_redis", lambda: (_ for _ in ()).throw(RuntimeError("down"))
    )
    # Must not raise, and read must return None when Redis is unavailable.
    await zalo_oa_health.record_oa_signature(ok=True)
    assert await zalo_oa_health.read_oa_signature_health() is None


@pytest.mark.asyncio
async def test_read_returns_none_when_empty(fake_redis):
    assert await zalo_oa_health.read_oa_signature_health() is None
