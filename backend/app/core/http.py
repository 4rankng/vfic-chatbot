"""Process-scoped singleton ``httpx.AsyncClient`` registry.

Why this exists (Tech-Lead Directive §4 "Reuse connections"): every per-request
``async with httpx.AsyncClient()`` construction pays a fresh DNS + TCP + TLS
handshake (~100-300 ms on the 2-vCPU droplet). On the chat hot path that overhead
multiplies across Zalo send, embedding, and email calls per turn. Reusing one
long-lived client per named service keeps warm connections in a pool and removes
that handshake cost from every outbound call.

Design:

- **Per-name clients, not one global.** Zalo Bot Platform, Zalo OA, Resend,
  OpenRouter embeddings, and the OA token-refresh endpoint all use different
  base URLs, auth schemes, and timeouts. Per-name isolation prevents auth-header
  bleed (Bot Platform uses a path token; OA uses an ``access_token`` header;
  Resend uses a ``Bearer`` header) and lets each service have its own pool
  sizing. Callers MUST pass auth headers per-request, never at construction —
  Zalo tokens refresh on a schedule and a client built with a stale header
  would never pick up the rotation.

- **Lazy + thread-safe.** The first call for a given name constructs the client
  inside an ``asyncio.Lock``; subsequent calls return the cached instance. The
  lock guards only the rare race at startup, not the hot path.

- **Lifespan-owned.** ``lifespan_http_clients`` is wired into ``app.main`` so
  clients are closed on shutdown (after RQ workers drain), releasing pooled
  connections cleanly.

- **RQ workers.** Workers don't run the FastAPI lifespan; they call
  ``aclose_all()`` from their own shutdown hook (see ``run_worker.py``). If they
  don't, the process exit reaps the sockets anyway — correctness is preserved,
  cleanliness is not.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Module-level registry: name -> live client. Populated lazily by
# ``get_http_client``; drained by ``aclose_all`` at shutdown.
_CLIENTS: dict[str, httpx.AsyncClient] = {}
# Serializes the construction step so two concurrent first-callers for the same
# name don't build two clients and leak one. Hot-path reads of an existing
# client do NOT take this lock — only the rare miss.
_LOCK: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Lazily allocate the asyncio.Lock on first use.

    Allocated inside the running loop so its bind is correct (Python 3.12 still
    warns on lock reuse across loops; allocating on first call avoids that).
    """
    global _LOCK
    if _LOCK is None:
        _LOCK = asyncio.Lock()
    return _LOCK


async def get_http_client(
    name: str,
    *,
    base_url: str | None = None,
    timeout: float | httpx.Timeout | None = None,
    headers: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> httpx.AsyncClient:
    """Return the process-scoped ``httpx.AsyncClient`` for ``name``.

    The first caller for a given name constructs the client with the supplied
    ``base_url`` / ``timeout`` / ``headers``; later callers receive the same
    instance and the kwargs they pass are ignored (document this at call sites:
    pass per-request ``timeout=`` to the httpx METHOD, not here, when a single
    name needs variable timeouts). Auth headers should be passed per-request,
    not at construction — see module docstring.

    ``name`` is a stable string key (e.g. ``"zalo_bot_send"``,
    ``"openrouter_embed"``); each name gets its own connection pool.
    """
    existing = _CLIENTS.get(name)
    if existing is not None:
        return existing
    async with _get_lock():
        # Re-check inside the lock: a concurrent awaiter may have built it.
        existing = _CLIENTS.get(name)
        if existing is not None:
            return existing
        s = settings or get_settings()
        # Build kwargs conditionally — httpx rejects base_url=None (must be
        # omitted, not None). Headers default to None which httpx accepts.
        client_kwargs: dict[str, Any] = {
            "timeout": timeout if timeout is not None else s.http_default_timeout,
            "headers": headers,
            "limits": httpx.Limits(
                max_keepalive_connections=s.http_max_keepalive_connections,
                max_connections=s.http_max_connections,
                keepalive_expiry=s.http_keepalive_expiry,
            ),
        }
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        client = httpx.AsyncClient(**client_kwargs)
        _CLIENTS[name] = client
        logger.debug(
            "http client registered name=%s base=%s keepalive=%d max=%d",
            name,
            base_url or "-",
            s.http_max_keepalive_connections,
            s.http_max_connections,
        )
        return client


async def aclose_all() -> None:
    """Close every registered client. Safe to call repeatedly (no-op if empty).

    Logs each close + the final pool stats so shutdown ordering is observable.
    Failures are logged but never propagate — a half-closed client must not
    poison the rest of shutdown.
    """
    if not _CLIENTS:
        return
    for name, client in list(_CLIENTS.items()):
        # Test-injected fakes may not implement aclose(); skip them. Real
        # httpx.AsyncClient instances always do.
        if not isinstance(client, httpx.AsyncClient):
            continue
        try:
            await client.aclose()
            logger.debug("http client closed name=%s", name)
        except Exception:  # noqa: BLE001
            logger.warning("http client close failed name=%s", name, exc_info=True)
    _CLIENTS.clear()


def register_test_client(name: str, client: Any) -> None:
    """Test-only seam: inject a fake client under ``name``.

    Production code never calls this. Tests use it to swap the singleton with a
    fake that records requests / returns canned responses, without needing to
    monkeypatch ``httpx.AsyncClient`` at the (now-removed) construction sites.
    The fake can be any object exposing the ``.post()`` / ``.get()`` coroutines
    the call site uses; it does NOT need to be an ``httpx.AsyncClient`` or an
    async-context-manager.

    ``aclose_all`` skips non-httpx entries, so test fakes are not asked to
    implement ``aclose``.
    """
    _CLIENTS[name] = client


@asynccontextmanager
async def lifespan_http_clients(app: Any) -> AsyncIterator[None]:
    """Lifespan wrapper: yields control to the app, closes all clients on exit.

    Wire into ``app.main.lifespan`` OUTSIDE the yield so the close runs after
    the engine-dispose step (DB engine close before HTTP client close lets any
    final DB-driven send complete). Pattern::

        @asynccontextmanager
        async def lifespan(app):
            ... startup ...
            async with lifespan_http_clients(app):
                yield
            await engine.dispose()
    """
    try:
        yield
    finally:
        await aclose_all()
