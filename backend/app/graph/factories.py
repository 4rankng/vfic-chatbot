"""Dependency factories for the graph's LLM/embedder wiring.

- ``build_deps`` wires the full ``GraphDeps`` for the chatbot worker.
- ``build_minimax_extractor`` — candidate extraction (persistence worker).
- ``make_minimax_llm_json`` — JSON-mode LLM for the knowledge training pipeline (ingest worker).

The port adapters (``graph/adapters.py``) and the process-wide LLM client cache
(``graph/client_cache.py``) live in their own composition modules; this module
keeps the LLM builders whose provider constructors tests monkeypatch, plus
``build_deps`` itself. langchain_openai is imported lazily inside each factory
so the web-process import path stays langchain-free. ``_build_cached_clients``
/ ``aclose_client_cache`` / ``reset_client_cache`` are re-exported for their
existing importers (workers, app shutdown, tests).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Callable, Sequence

from app.core.config import get_settings
from app.graph.adapters import (
    _DirectContextAdapter,
    _FaqBypassAdapter,
    _RuntimePolicyAdapter,
)
from app.graph.client_cache import build_cached_clients as _build_cached_clients
from app.graph.client_cache import (
    aclose_client_cache as aclose_client_cache,
    reset_client_cache as reset_client_cache,
)
from app.graph.clients import (
    MiniMaxAgent,
    _chat_for_role,
    _custom_chat,
    _minimax_chat,
    _openrouter_chat,
)
from app.graph.safety import DeterministicReplyPolicy
from app.graph.types import GraphDeps

logger = logging.getLogger(__name__)


def build_minimax_extractor():
    """MiniMax extractor (safety model, temp 0) for candidate extraction."""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _chat_for_role("safety", temperature=0.0)

    async def extractor(system: str, user: str) -> str:
        return (
            await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        ).content

    return extractor


def make_minimax_llm_json(
    *,
    minimax_api_key: str | None = None,
    openrouter_api_key: str | None = None,
):
    """(system, user) -> json_text callable for the LLM training pipeline.

    OpenAI-compatible MiniMax client with JSON-object response mode. Falls back to the
    agent model when MINIMAX_DIGEST_MODEL is unset. Imported lazily by the ingest worker
    only, so the app/tests never need langchain-openai at import time.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _chat_for_role(
        "digest",
        temperature=0.1,
        json_mode=True,
        minimax_api_key=minimax_api_key,
        openrouter_api_key=openrouter_api_key,
    )

    async def _call(system: str, user: str) -> str:
        return (
            await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        ).content

    return _call


def _build_fast_llm(*, minimax_config, openrouter_config, custom_config=None):
    """Build the optional fast-tier LLM for low-complexity intents (Phase 5).

    Returns ``None`` when no fast model is configured on the active provider —
    ``MiniMaxAgent`` then no-ops the ``use_fast`` switch (every turn uses the
    primary reasoning model, the pre-tiering default).

    The fast model is built directly (not via ``_chat_for_role``) because the
    role factory hard-codes the agent/safety model names. Here we explicitly use
    ``minimax_fast_model`` / ``openrouter_fast_model`` / ``custom_llm_fast_model``
    so the tier is genuine.

    Only the single active provider's fast model is built. Cross-provider
    failover applies to the reasoning path (see ``_build_failover_chain``); a
    fast-tier turn that runs out of capacity escalates through the same chain.
    """
    s = get_settings()
    mm_fast = (getattr(s, "minimax_fast_model", "") or "").strip()
    or_fast = (getattr(s, "openrouter_fast_model", "") or "").strip()

    try:
        if minimax_config.enabled and mm_fast and minimax_config.api_key:
            if minimax_config.default_provider != "openrouter":
                return _minimax_chat(mm_fast, temperature=0.3, api_key=minimax_config.api_key)
        if openrouter_config.enabled and or_fast and openrouter_config.api_key:
            return _openrouter_chat(
                or_fast,
                temperature=0.3,
                timeout=s.openrouter_request_timeout,
                api_key=openrouter_config.api_key,
                capture_reasoning=True,
            )
        # The custom provider's fast model is admin-configured (env fallback),
        # so read it off the resolved config instead of settings alone. Blank
        # fast model inherits the agent model — one model id is enough.
        if (
            custom_config is not None
            and custom_config.enabled
            and (custom_config.fast_model or custom_config.agent_model)
            and custom_config.api_key
            and custom_config.base_url
            and custom_config.default_provider == "custom"
        ):
            return _custom_chat(
                custom_config.fast_model or custom_config.agent_model,
                temperature=0.3,
                api_key=custom_config.api_key,
                base_url=custom_config.base_url,
            )
        return None
    except Exception:  # noqa: BLE001
        logger.warning("fast-tier LLM build failed; primary-only tier", exc_info=True)
        return None


def _build_failover_chain(
    *,
    minimax_config,
    openrouter_config,
    custom_config,
    failover_order: Sequence[str] = ("minimax", "openrouter", "custom"),
):
    """Clients for every configured provider EXCEPT the active one, in order.

    The operator does not nominate a spare: any provider they have enabled with
    a usable credential is eligible, so enabling OpenRouter alongside MiniMax is
    enough to survive a spent MiniMax plan. ``failover_order`` is the
    operator-ranked preference stored with the integration settings (see
    ``resolve_llm_failover_order``); the canonical default reproduces the
    historic order — the other first-class provider, then the generic
    OpenAI-compatible slot. Unranked names trail the ranked ones, so a partial
    operator order only moves the providers they actually ranked.

    Build failures are swallowed per-provider: a misconfigured spare must not
    take down the turn, it just does not join the chain.
    """
    s = get_settings()
    active = minimax_config.default_provider
    chain: list[object] = []

    def _add(label: str, build):
        try:
            client = build()
        except Exception:  # noqa: BLE001 — a broken spare simply does not join
            logger.warning("failover provider %s unavailable; skipping", label, exc_info=True)
            return
        if client is not None:
            chain.append(client)

    # (rank name, log label, builder) — the custom slot keeps its legacy
    # "fallback" log label while ranking under its canonical provider name.
    candidates: list[tuple[str, str, Callable[[], object]]] = []
    if active != "minimax" and minimax_config.enabled and minimax_config.api_key:
        candidates.append(
            (
                "minimax",
                "minimax",
                # DB-managed model id wins over the env default, matching how
                # the active provider resolves its model.
                lambda: _minimax_chat(
                    minimax_config.agent_model or s.minimax_agent_model,
                    temperature=0.3,
                    api_key=minimax_config.api_key,
                ),
            )
        )
    if active != "openrouter" and openrouter_config.enabled and openrouter_config.api_key:
        candidates.append(
            (
                "openrouter",
                "openrouter",
                lambda: _openrouter_chat(
                    openrouter_config.agent_model,
                    temperature=0.3,
                    timeout=s.openrouter_request_timeout,
                    api_key=openrouter_config.api_key,
                    capture_reasoning=True,
                ),
            )
        )
    if active != "custom" and custom_config is not None and custom_config.usable:
        candidates.append(
            (
                "custom",
                "fallback",
                lambda: _custom_chat(
                    custom_config.agent_model,
                    temperature=0.3,
                    api_key=custom_config.api_key,
                    base_url=custom_config.base_url,
                ),
            )
        )

    rank = {name: index for index, name in enumerate(failover_order)}
    # Stable sort: unranked candidates keep their canonical append order.
    candidates.sort(
        key=lambda candidate: (
            rank[candidate[0]] if candidate[0] in rank else len(rank)
        )
    )
    for _, label, build in candidates:
        _add(label, build)
    return chain


async def resolve_page_project_scope(db, conversation_id) -> tuple[str, ...] | None:
    """Projects assigned to the Page this conversation arrived on.

    ``None`` means "do not scope": the conversation is not on a multi-Page
    provider, or the Page has no assignments. Returning an empty tuple instead
    would scope every catalog query to nothing and mute the bot, which is a
    worse failure than the pre-scoping behaviour.
    """
    from sqlalchemy import select

    from app.channels.types import PROVIDER_FACEBOOK_MESSENGER
    from app.models.contact import ContactChannelIdentity
    from app.models.conversation import Conversation
    from app.services.retrieval import RetrievalRepository

    row = (
        await db.execute(
            select(ContactChannelIdentity.provider, ContactChannelIdentity.account_key)
            .join(Conversation, Conversation.channel_identity_id == ContactChannelIdentity.id)
            .where(Conversation.id == conversation_id)
        )
    ).first()
    if row is None or row.provider != PROVIDER_FACEBOOK_MESSENGER:
        return None
    project_ids = await RetrievalRepository(db).project_ids_for_page(row.account_key)
    return tuple(project_ids) or None


async def build_deps(db, *, session_factory=None, conversation_id=None, page_project_ids=None):
    """Wire the full GraphDeps for one chatbot turn (agent + safety + embedder + zalo).

    The expensive LLM clients + embedder are cached process-wide (see
    ``_build_cached_clients``); this function only re-binds the per-turn pieces:
    the db session, retrieval/lead/faq_bypass adapters, the zalo sender (with
    its token-refresh closure), and the followup gate.

    ``session_factory`` (optional, an ``async_sessionmaker``) enables parallel tool
    dispatch: each concurrent tool call opens its own session via the factory
    instead of sharing ``db`` (which is NOT safe for concurrent use).

    ``conversation_id`` (optional) binds every retrieval port for this turn to
    the Projects assigned to the Facebook Page the conversation arrived on;
    Zalo conversations resolve to the deployment-wide catalog. The scope must
    reach every repository built here — a single unscoped one leaks another
    Page's catalog back into the answer. ``page_project_ids`` overrides the
    lookup directly, which keeps the wiring testable without a live Page.
    """
    from app.services.conversation import ConversationService
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.profile_enrichment import ProfileEnrichmentService
    from app.services.retrieval import RetrievalRepository
    from app.services.zalo_oa_service import ZaloOASender
    from app.services.zalo_sender import ZaloChannelSender

    clients = await _build_cached_clients(db)
    integration_settings = IntegrationSettingsService(db, settings=get_settings())
    if page_project_ids is None and conversation_id is not None:
        page_project_ids = await resolve_page_project_scope(db, conversation_id)

    # Zalo config is resolved per-turn (cheap — Redis-cached via cached_zalo_config)
    # so a rotated OA token takes effect on the very next turn without invalidating
    # the expensive LLM client cache.
    zalo_config = await integration_settings.resolve_zalo()
    zalo_sender = ZaloChannelSender(
        zalo_config,
        refresh=lambda: integration_settings.refresh_oa_access_token(),
    )
    # The inline profile lookup is hard-bounded by run_turn. Never attach the
    # single-use refresh-token flow to a cancellable task: a cancellation after
    # Zalo rotates but before we durably store the pair would strand the OA.
    # persistence_low retains the uncapped refresh-aware fallback.
    profile_sender = ZaloOASender(access_token=zalo_config.oa_access_token)

    # Jev turn-decision fan-out (one systemone call per turn). The resolve is
    # Redis-cached like the other integrations, so the enable toggle or a
    # rotated key takes effect on the next turn. None when disabled or
    # unconfigured: the runner then routes on the neutral agent fallback. The
    # same call also judges the candidate's gender for addressing.
    from app.graph.decisions import JevDecisionClient

    jev_config = await integration_settings.resolve_jev()
    turn_decisions = (
        JevDecisionClient(api_key=jev_config.api_key, model=jev_config.model)
        if jev_config.usable
        else None
    )

    async def _enrich_oa_profile(zalo_id: str, user_id: str) -> bool:
        # Production chatbot turns provide a session factory. Keep the provider
        # request and profile update isolated from the main turn transaction so
        # a slow OA response never pins that transaction or connection.
        if session_factory is not None:
            async with session_factory() as profile_db:
                return await ProfileEnrichmentService(
                    profile_db, profile_sender
                ).enrich_oa_user(zalo_id, user_id=user_id)
        return await ProfileEnrichmentService(db, profile_sender).enrich_oa_user(
            zalo_id, user_id=user_id
        )

    # Parallel tool dispatch: each concurrent tool call gets its own session so
    # the shared ``db`` is never used concurrently. Lazy import keeps the graph
    # layer free of concrete-service imports at module load.
    make_retrieval = None
    if session_factory is not None:

        @asynccontextmanager
        async def _make_retrieval():
            async with session_factory() as session:
                yield RetrievalRepository(session, page_project_ids=page_project_ids)

        make_retrieval = _make_retrieval

    return GraphDeps(
        db=db,
        agent=MiniMaxAgent(
            clients.agent_llm,
            clients.embedder,
            fast_llm=clients.fast_llm,
            fallback_llms=clients.failover_llms,
        ),
        embedder=clients.embedder,
        zalo=zalo_sender,
        conversation=ConversationService(db),
        retrieval=RetrievalRepository(db, page_project_ids=page_project_ids),
        reply_policy=DeterministicReplyPolicy(),
        make_retrieval=make_retrieval,
        lead=_build_lead_context(db),
        lead_gender=_build_lead_gender(db),
        faq_bypass=_FaqBypassAdapter(db, clients.embedder, page_project_ids=page_project_ids),
        followup_allowed=_make_followup_allowed(db),
        enrich_oa_profile=_enrich_oa_profile,
        runtime_policy=_RuntimePolicyAdapter(db),
        direct_context=_DirectContextAdapter(db),
        proactive_state=_build_proactive_state(db),
        delivery_statuses=_build_delivery_statuses(),
        turn_decisions=turn_decisions,
    )


def _make_followup_allowed(db):
    from app.composition.recruitment import build_followup_eligibility

    adapter = build_followup_eligibility(db)
    return adapter.allowed


def _build_lead_context(db):
    from app.composition.recruitment import build_lead_context

    return build_lead_context(db)


def _build_lead_gender(db):
    from app.composition.recruitment import build_lead_gender

    return build_lead_gender(db)


def _build_proactive_state(db):
    from app.composition.recruitment import build_proactive_state

    return build_proactive_state(db)


def _build_delivery_statuses():
    from app.composition.conversation_messaging import build_delivery_status_values

    return build_delivery_status_values()
