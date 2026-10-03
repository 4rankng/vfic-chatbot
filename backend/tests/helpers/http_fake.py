"""Test helpers for the process-scoped httpx singleton registry.

Production code uses ``app.core.http.get_http_client(name)`` to obtain a long-lived
``httpx.AsyncClient``. Tests need to swap that client with a fake that records
requests and returns canned responses, WITHOUT monkeypatching
``httpx.AsyncClient`` at the (now-removed) construction sites.

Two helpers:

- ``FakeHttpClient`` — a plain object with ``.post()`` / ``.get()`` coroutines
  that record calls and return a queued response. NOT an async-context-manager
  (the singleton returns the client directly, not via ``async with``).
- ``register_fake_client(name, fake)`` — wraps
  ``app.core.http.register_test_client`` for ergonomic test use; pairs with the
  ``reset_http_registry`` autouse fixture to keep tests isolated.

Usage::

    async def test_something(reset_http_registry):
        fake = FakeHttpClient(responses=[{"ok": True}])
        register_fake_client("zalo_bot", fake)
        result = await svc.ZaloBotSender().send_message(...)
        assert fake.calls[0]["url"] == "https://..."
"""

from __future__ import annotations

from typing import Any, Callable

from app.core import http as _http_module
from app.core.http import register_test_client


class FakeHttpClient:
    """A minimal stand-in for ``httpx.AsyncClient`` for unit tests.

    Construct with a list of response payloads (each returned by ``.json()``
    on the fake response), a single ``side_effect`` exception to raise, or a
    ``side_effect`` CALLABLE that routes on the request and returns a payload (or
    a ready :class:`_FakeResponse`). Calls are recorded in ``self.calls`` for
    assertions.

    Prefer the callable form whenever one client serves more than one endpoint —
    e.g. a provider whose forward and reverse calls hit the same host. A
    positional queue there hands the payloads out in call order, so the moment
    the number of calls changes the reverse lookup receives a forward body (and
    fails as "no names") while the test still passes or fails for reasons that
    have nothing to do with the code under test.

    Mirrors only the surface area the migrated call sites use: ``.post()`` and
    ``.get()`` returning an object with ``.json()`` / ``.status_code`` /
    ``.text`` / ``.raise_for_status()``.
    """

    def __init__(
        self,
        *,
        responses: list[Any] | None = None,
        status_codes: list[int] | None = None,
        side_effect: BaseException | Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._responses = list(responses) if responses else []
        self._status_codes = list(status_codes) if status_codes else []
        self._side_effect = side_effect
        self.calls: list[dict[str, Any]] = []

    def _next_response(self) -> Any:
        if not self._responses:
            return {"ok": True}
        return self._responses.pop(0)

    def _next_status(self) -> int:
        if not self._status_codes:
            return 200
        return self._status_codes.pop(0)

    def _respond(self, request: dict[str, Any]) -> _FakeResponse:
        """The response for ``request``: routed by a callable, else queued."""
        if self._side_effect is None:
            return _FakeResponse(self._next_response(), self._next_status())
        if callable(self._side_effect):
            result = self._side_effect(request)
            if isinstance(result, _FakeResponse):
                return result
            return _FakeResponse(result, 200)
        raise self._side_effect

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        data: Any = None,
        headers: Any = None,
        params: Any = None,
        **kw: Any,
    ) -> _FakeResponse:
        request = {
            "method": "POST",
            "url": url,
            "json": json,
            "data": data,
            "headers": headers,
            "params": params,
        }
        self.calls.append(request)
        return self._respond(request)

    async def get(
        self,
        url: str,
        *,
        params: Any = None,
        headers: Any = None,
        **kw: Any,
    ) -> _FakeResponse:
        request = {"method": "GET", "url": url, "params": params, "headers": headers}
        self.calls.append(request)
        return self._respond(request)


class _FakeResponse:
    def __init__(self, payload: Any, status_code: int) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)[:500]

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def register_fake_client(name: str, fake: FakeHttpClient) -> FakeHttpClient:
    """Register ``fake`` as the singleton for ``name``; returns ``fake``."""
    register_test_client(name, fake)
    return fake


def reset_registry() -> None:
    """Clear the singleton registry (test isolation)."""
    _http_module._CLIENTS.clear()
    _http_module._LOCK = None
