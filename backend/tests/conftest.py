"""Shared pytest configuration for VFIC backend unit tests.

All tests in this directory are pure unit tests — no live DB, no Redis,
no external services. Tests needing infrastructure live in
``tests/integration/`` and are selected explicitly; the unit lane fails any
test that would open a real outbound connection (see ``_block_external_http``).
"""

import socket

import httpx
import pytest

# Loopback hosts a unit test may legitimately talk to. ``testserver`` is the
# conventional base_url of an in-process ASGI transport.
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}

# The only httpx transports that open a real socket. Every other transport
# (MockTransport, ASGITransport, Starlette's test transport, a test double) is
# offline by construction, so a fake client registered against an
# external-looking host must keep working.
_REAL_NETWORK_TRANSPORTS = (httpx.HTTPTransport, httpx.AsyncHTTPTransport)


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


@pytest.fixture(autouse=True)
async def _reset_http_singleton_registry():
    """Clear the httpx singleton registry (app.core.http) around every test.

    Tests that need a fake HTTP client register it via
    ``tests.helpers.http_fake.register_fake_client``; this fixture guarantees
    no fake (and no real client) leaks from one test into the next. It also
    forces each test to construct its clients explicitly instead of inheriting
    one, which is why the outbound guard below matters.
    """
    from app.core import http as _http_module

    _http_module._CLIENTS.clear()
    _http_module._LOCK = None
    yield
    _http_module._CLIENTS.clear()
    _http_module._LOCK = None


@pytest.fixture(autouse=True)
def _block_external_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on an unstubbed outbound connection.

    The integration lane has the same guard (``tests/integration/conftest.py``);
    without it here, a unit test that forgets its stub would silently make a
    live request — cost, latency, nondeterminism, and in CI a hang until the
    job budget fires. Loopback is allowed so tests may talk to a local server,
    and offline transports (mock/ASGI) are allowed against any host because
    they never open a socket.
    """

    original_request = httpx.AsyncClient.request
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def assert_local(address) -> None:
        if not isinstance(address, tuple) or not address:
            return  # AF_UNIX paths and other non-INET addresses are not outbound HTTP
        host = str(address[0])
        if host not in LOCAL_HOSTS:
            raise AssertionError(f"external network is forbidden in unit tests: {host}")

    def guarded_connect(self, address):
        assert_local(address)
        return original_connect(self, address)

    def guarded_connect_ex(self, address):
        assert_local(address)
        return original_connect_ex(self, address)

    async def guarded_request(self, method, url, *args, **kwargs):
        target = httpx.URL(url)
        if target.is_relative_url:
            target = self.base_url.join(target)
        if isinstance(self._transport_for_url(target), _REAL_NETWORK_TRANSPORTS):
            if target.host not in LOCAL_HOSTS:
                raise AssertionError(
                    f"external HTTP is forbidden in unit tests: {target.host}"
                )
        return await original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", guarded_request)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
