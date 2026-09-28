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
repo, lead adapter, zalo config + sender with its refresh closure, followup
gate).

The candidate-extraction clients (the extractor LLM + an embedder) live in a
second, independently-keyed bundle built by ``build_cached_extraction``. The
persistence queue runs one job per SENT reply and used to construct both per
job — a fresh langchain client (with its own httpx pool) and TLS handshake for
every reply. ``aclose_client_cache`` tears that bundle down on the same
shutdown path as the turn bundle, so no pool is leaked at exit.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from app.core.config import get_settings
from app.graph.clients import _chat_for_role, build_embedder
from app.graph.llm import Embedder
from app.graph.providers import LlmProvider

logger = logging.getLogger(__name__)


@dataclass
class _CachedClients:
    agent_llm: object
    fast_llm: object | None
    # Typed: ``GraphDeps`` and ``MiniMaxAgent`` both take an ``Embedder``, and an
    # ``object`` here made every construction site pass an unassignable value.
    embedder: Embedder
    # Ordered clients for the other configured providers; empty when the
    # operator has only one provider enabled.
    failover_llms: list = field(default_factory=list)


@dataclass
class _CachedExtraction:
    """Process-wide candidate-extraction clients (extractor LLM + embedder).

    Same lifecycle as :class:`_CachedClients` and closed by the same
    ``aclose_client_cache`` sweep; cached separately so the persistence queue
    never pays to build the agent/fast/failover chain it does not use.
    """

    extractor_llm: object
    extractor: object
    embedder: object


_client_cache: dict[str, _CachedClients] = {}
_extraction_cache: dict[str, _CachedExtraction] = {}
_client_cache_lock = asyncio.Lock()
_retired_client_bundles: list[_CachedClients | _CachedExtraction] = []
_client_retirement_tasks: set[asyncio.Task[None]] = set()
_CLIENT_RETIREMENT_GRACE_SECONDS = 600.0


async def _close_client_bundles(
    bundles: Sequence[_CachedClients | _CachedExtraction],
) -> None:
    cancellation: asyncio.CancelledError | None = None
    close_callbacks: list[tuple[str, object, object]] = []
    for bundle in bundles:
        if isinstance(bundle, _CachedExtraction):
            chat_clients: list[tuple[str, object]] = [
                ("extractor LLM", bundle.extractor_llm)
            ]
        else:
            chat_clients = [
                ("agent LLM", bundle.agent_llm),
                ("fast LLM", bundle.fast_llm),
            ]
        for name, client in chat_clients:
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


def _schedule_client_retirement(
    bundles: list[_CachedClients] | list[_CachedExtraction],
) -> None:
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


async def _provider_cache_key(db) -> str:
    """The settings-version key both bundles are invalidated by.

    Covers only the LLM providers (minimax + openrouter + custom LLM) whose
    settings drive client construction. Zalo is deliberately excluded — it
    feeds only the per-turn ``ZaloChannelSender`` (resolved separately in
    ``build_deps``), so a Zalo OA token refresh must NOT invalidate the
    expensive LLM clients.
    """
    from app.core.cache import cache_version

    mm_version = await cache_version("integration_minimax")
    or_version = await cache_version("integration_openrouter")
    fb_version = await cache_version("integration_custom_llm")
    return f"mm:{mm_version}|or:{or_version}|fb:{fb_version}"


async def build_cached_clients(db) -> _CachedClients:  # noqa: RUF029 (async for lock)
    """Return the cached LLM client bundle, building it once per settings version."""
    from app.services.integration_settings import IntegrationSettingsService

    s = get_settings()
    integration_settings = IntegrationSettingsService(db, settings=s)
    cache_key = await _provider_cache_key(db)

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
            # ``MinimaxRuntimeConfig.default_provider`` is a plain ``str`` while
            # the client wants the ``LlmProvider`` literal. The settings layer
            # guarantees the value via ``_shared._provider_value``, which returns
            # one of ``_SELECTABLE_PROVIDERS`` or "minimax".
            default_provider=cast(LlmProvider, minimax_config.default_provider),
            reasoning_mode=minimax_config.reasoning_mode,
            max_tokens=minimax_config.agent_max_tokens,
            openrouter_agent_model=openrouter_config.agent_model,
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
    _extraction_cache.clear()
    _retired_client_bundles.clear()
    for task in _client_retirement_tasks:
        task.cancel()
    _client_retirement_tasks.clear()


async def build_cached_extraction(db) -> _CachedExtraction:  # noqa: RUF029 (async for lock)
    """Return the cached candidate-extraction bundle, built once per settings version.

    The persistence queue runs one job per SENT reply, so building the extractor
    LLM and an embedder per job meant a fresh langchain client (with its own
    httpx pool) plus a fresh TLS handshake for every reply. Keyed by the same
    provider-settings version as :func:`build_cached_clients`, so a rotated
    provider key still takes effect on the next job.
    """
    from app.graph.factories import build_minimax_extractor
    from app.services.integration_settings import IntegrationSettingsService

    s = get_settings()
    cache_key = await _provider_cache_key(db)

    cached = _extraction_cache.get(cache_key)
    if cached is not None:
        return cached

    async with _client_cache_lock:
        cached = _extraction_cache.get(cache_key)
        if cached is not None:
            return cached
        openrouter_config = await IntegrationSettingsService(db, settings=s).resolve_openrouter()
        # The extractor callable closes over the langchain client it builds, so
        # both are cached together and closed together.
        bundle = _CachedExtraction(
            extractor_llm=_chat_for_role("extractor", temperature=0.0),
            extractor=build_minimax_extractor(),
            embedder=build_embedder(s, openrouter_api_key=openrouter_config.api_key),
        )
        displaced = list(_extraction_cache.values())
        _extraction_cache.clear()  # only one active version at a time
        _extraction_cache[cache_key] = bundle
        _schedule_client_retirement(displaced)
        logger.info("extraction_client_cache built key=%s", cache_key)
        return bundle


async def aclose_client_cache() -> None:
    """Close active and safely retired provider pools owned by this event loop."""
    retirement_tasks = list(_client_retirement_tasks)
    for task in retirement_tasks:
        task.cancel()
    if retirement_tasks:
        await asyncio.gather(*retirement_tasks, return_exceptions=True)
    _client_retirement_tasks.clear()
    bundles = (
        list(_client_cache.values())
        + list(_extraction_cache.values())
        + list(_retired_client_bundles)
    )
    _client_cache.clear()
    _extraction_cache.clear()
    _retired_client_bundles.clear()
    unique_bundles = list({id(bundle): bundle for bundle in bundles}.values())
    await _close_client_bundles(unique_bundles)
