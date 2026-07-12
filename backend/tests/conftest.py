"""Shared pytest configuration for VFIC backend unit tests.

All tests in this directory are pure unit tests — no live DB, no Redis,
no external services. Integration tests requiring infrastructure have
been moved out.
"""

import pytest


class _NoopRedis:
    """Async Redis double that always reports a miss and discards writes.

    Isolates unit tests from any locally-running Redis so cached values never
    leak across tests. Tests that exercise the cache directly supply their own
    fake (see ``tests/test_preamble_cache.py``).
    """

    _instance = None

    async def get(self, key):
        return None

    async def set(self, key, value, *, ex=None):
        return "OK"

    async def incr(self, key):
        return 1

    async def delete(self, key):
        return 0


@pytest.fixture(autouse=True)
def _isolate_redis(monkeypatch):
    """Point both redis singletons at a no-op double for every unit test."""
    monkeypatch.setattr("app.core.redis.get_redis", lambda: _NoopRedis())
    monkeypatch.setattr("app.core.cache.get_redis", lambda: _NoopRedis())
