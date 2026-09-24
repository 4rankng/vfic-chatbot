"""The unit lane must fail an unstubbed outbound connection, not make it.

Counterpart of ``tests/integration/test_harness_smoke.py``: that file proves the
integration lane blocks external network access. These tests prove the unit
lane (``tests/conftest.py::_block_external_http``) does too, while leaving
loopback and offline test transports usable.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from fastapi import FastAPI


async def test_unstubbed_httpx_request_fails_with_the_offending_host() -> None:
    """A real client with no stub/transport override must not reach the network."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(
            AssertionError, match=r"external HTTP is forbidden in unit tests: api\.example\.test"
        ):
            await client.post("https://api.example.test/v2/messages", json={"text": "hi"})


def test_unstubbed_socket_connect_fails_with_the_offending_host() -> None:
    with pytest.raises(
        AssertionError, match=r"external network is forbidden in unit tests: 203\.0\.113\.1"
    ):
        socket.socket().connect(("203.0.113.1", 443))


def test_loopback_socket_connect_is_allowed() -> None:
    """The guard must not block the local services a unit test may stand up."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket()
    client.settimeout(5)
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()


async def test_stubbed_client_against_an_external_host_still_works() -> None:
    """A mock transport never opens a socket, so its host must not be blocked."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://api.example.test"
    ) as client:
        response = await client.get("/v2/messages")

    assert response.status_code == 200


async def test_asgi_transport_client_still_reaches_the_app() -> None:
    """In-process ASGI requests use the conventional fake host ``test``/``testserver``."""
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.json() == {"status": "ok"}
