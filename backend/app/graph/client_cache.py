"""Process-wide LLM client cache with async retirement.

The ChatOpenAI clients + embedder are expensive to construct (langchain_openai
import + httpx/pydantic wiring). Caching them avoids rebuilding on every turn.
Keyed by the minimax + openrouter + custom integration-settings cache versions
ONLY — the providers whose settings actually drive agent_llm / embedder /
fast_llm construction. Zalo is deliberately excluded: its config feeds the
per-turn ZaloChannelSender (resolved fresh in ``build_deps``), so an OA token
rotation invalidating this cache would force a needless 5-7s LLM-client rebuild.

Scope of the win:
- Direct/ASGI path (start_direct_chat_turn): multiple turns share one event
  loop + one cache in the web process → the 2nd+ turn skips rebuild.
- RQ fork-per-job path: each forked child starts with an empty cache (the
  parent's cache cannot be inherited — ChatOpenAI wraps an httpx pool whose
  sockets must not be shared across fork()). So under default RQ each child
  builds once and exits; the per-turn win there is the asyncio.gather over the
  resolve_* calls, not this cache. Moving chatbot turns off fork-per-job
  (SimpleWorker) is what makes this cache bite on the worker path.

``build_cached_clients`` is the single constructor; ``factories.build_deps``
reads the cache and only re-binds the per-turn pieces (db session, retrieval
repo, lead adapter, faq_bypass adapter, zalo config + sender with its refresh
closure, followup gate).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.graph.clients import _chat_for_role, build_embedder

logger = logging.getLogger(__name__)


@dataclass
class _CachedClients:
    agent_llm: object
    fast_llm: object | None
    embedder: object
    # Ordered clients for the other configured providers; empty when the
    # operator has only one provider enabled.
    failover_llms: list = field(default_factory=list)


_client_cache: dict[str, _CachedClients] = {}
_client_cache_lock = asyncio.Lock()
_retired_client_bundles: list[_CachedClients] = []
_client_retirement_tasks: set[asyncio.Task[None]] = set()
_CLIENT_RETIREMENT_GRACE_SECONDS = 600.0


async def _close_client_bundles(bundles: list[_CachedClients]) -> None:
    cancellation: asyncio.CancelledError | None = None
    close_callbacks: list[tuple[str, object, object]] = []
    for bundle in bundles:
        for name, client in (("agent LLM", bundle.agent_llm), ("fast LLM", bundle.fast_llm)):
            root = getattr(client, "root_async_client", None)
            close = getattr(root, "close", None)
            if close is not None:
                close_callbacks.append((name, root, close))
        embed_client = getattr(bundle.embedder, "_client", None)
        embed_aio = getattr(embed_client, "aio", None)
        embed_close = getattr(embed_aio, "aclose", None)
        if embed_close is not None:
            close_callbacks.append(("embedder", embed_aio, embed_close))

    closed_owners: set[int] = set()
    for name, owner, close in close_callbacks:
        if id(owner) in closed_owners:
            continue
        closed_owners.add(id(owner))
        try:
            result = close()  # type: ignore[operator]
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
            logger.warning("client pool close cancelled resource=%s", name, exc_info=True)
        except Exception:  # noqa: BLE001 - close remaining independent pools
            logger.warning("client pool close failed resource=%s", name, exc_info=True)
    if cancellation is not None:
        raise cancellation


def _schedule_client_retirement(bundles: list[_CachedClients]) -> None:
    if not bundles:
        return
    _retired_client_bundles.extend(bundles)

    async def retire_after_grace() -> None:
        await asyncio.sleep(_CLIENT_RETIREMENT_GRACE_SECONDS)
        await _close_client_bundles(bundles)
        for bundle in bundles:
            if bundle in _retired_client_bundles:
                _retired_client_bundles.remove(bundle)

    task = asyncio.create_task(retire_after_grace())
    _client_retirement_tasks.add(task)
    task.add_done_callback(_client_retirement_tasks.discard)


async def build_cached_clients(db) -> _CachedClients:  # noqa: RUF029 (async for lock)
    """Return the cached LLM client bundle, building it once per settings version.

    The cache key covers only the LLM providers (minimax + openrouter) whose
    settings actually drive ``agent_llm`` / ``embedder`` / ``fast_llm``
    construction. Zalo config is deliberately excluded — it feeds only the
    per-turn ``ZaloChannelSender`` (resolved separately in ``build_deps``), so
    a Zalo OA token refresh must NOT invalidate the expensive LLM clients.
    """
    from app.core.cache import cache_version
    from app.services.integration_settings import IntegrationSettingsService

    s = get_settings()
    integration_settings = IntegrationSettingsService(db, settings=s)

    mm_version = await cache_version("integration_minimax")
    or_version = await cache_version("integration_openrouter")
    fb_version = await cache_version("integration_custom_llm")
    cache_key = f"mm:{mm_version}|or:{or_version}|fb:{fb_version}"

    cached = _client_cache.get(cache_key)
    if cached is not None:
        return cached

    async with _client_cache_lock:
        # Re-check inside the lock: a concurrent turn may have built it.
        cached = _client_cache.get(cache_key)
        if cached is not None:
            return cached

        # Sequential: both resolves share the same ``db`` session, and
        # SQLAlchemy AsyncSession does NOT permit concurrent operations on one
        # connection (InvalidRequestError: "provisioning a new connection;
        # concurrent operations are not permitted"). On a cache hit each resolve
        # is a sub-ms Redis read; the cold path (first turn after restart) pays
        # two serial DB round-trips instead of one, but that happens once per
        # process lifetime.
        minimax_config = await integration_settings.resolve_minimax()
        openrouter_config = await integration_settings.resolve_openrouter()
        custom_config = await integration_settings.resolve_custom_llm()
        failover_order = await integration_settings.resolve_llm_failover_order()
        # Imported here (not at module top) because these builders live in the
        # composition root alongside their monkeypatched provider constructors.
        from app.graph.factories import _build_failover_chain, _build_fast_llm

        agent_llm = _chat_for_role(
            "agent",
            temperature=0.3,
            custom_enabled=custom_config.enabled,
            custom_config=custom_config,
            minimax_api_key=minimax_config.api_key,
            openrouter_api_key=openrouter_config.api_key,
            minimax_enabled=minimax_config.enabled,
            openrouter_enabled=openrouter_config.enabled,
            default_provider=minimax_config.default_provider,
            openrouter_agent_model=openrouter_config.agent_model,
            openrouter_safety_model=openrouter_config.safety_model,
            openrouter_digest_model=openrouter_config.digest_model,
        )
        embedder = build_embedder(s, openrouter_api_key=openrouter_config.api_key)
        fast_llm = _build_fast_llm(
            minimax_config=minimax_config,
            openrouter_config=openrouter_config,
            custom_config=custom_config,
        )
        failover_llms = _build_failover_chain(
            minimax_config=minimax_config,
            openrouter_config=openrouter_config,
            custom_config=custom_config,
            failover_order=failover_order,
        )
        bundle = _CachedClients(
            agent_llm=agent_llm,
            fast_llm=fast_llm,
            embedder=embedder,
            failover_llms=failover_llms,
        )
        displaced = list(_client_cache.values())
        _client_cache.clear()  # only one active version at a time
        _client_cache[cache_key] = bundle
        _schedule_client_retirement(displaced)
        logger.info("llm_client_cache built key=%s", cache_key)
        return bundle


def reset_client_cache() -> None:
    """Clear the LLM client cache. Tests use this between cases."""
    _client_cache.clear()
    _retired_client_bundles.clear()
    for task in _client_retirement_tasks:
        task.cancel()
    _client_retirement_tasks.clear()


async def aclose_client_cache() -> None:
    """Close active and safely retired provider pools owned by this event loop."""
    retirement_tasks = list(_client_retirement_tasks)
    for task in retirement_tasks:
        task.cancel()
    if retirement_tasks:
        await asyncio.gather(*retirement_tasks, return_exceptions=True)
    _client_retirement_tasks.clear()
    bundles = list(_client_cache.values()) + list(_retired_client_bundles)
    _client_cache.clear()
    _retired_client_bundles.clear()
    unique_bundles = list({id(bundle): bundle for bundle in bundles}.values())
    await _close_client_bundles(unique_bundles)
