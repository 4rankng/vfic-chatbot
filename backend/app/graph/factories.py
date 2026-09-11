"""Dependency factories for the graph's LLM/embedder wiring.

- ``build_deps`` wires the full ``GraphDeps`` for the chatbot worker.
- ``build_minimax_extractor`` — candidate extraction (persistence worker).
- ``make_minimax_llm_json`` — JSON-mode LLM for the knowledge training pipeline (ingest worker).

langchain_openai is imported lazily inside each factory so the web-process import path
stays langchain-free.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.graph.clients import (
    MiniMaxAgent,
    _chat_for_role,
    _custom_chat,
    _minimax_chat,
    _openrouter_chat,
    build_embedder,
)
from app.recruitment.domain.recommendation import (
    is_salary_profile_statement,
    parse_salary_band,
)
from app.graph.safety import DeterministicReplyPolicy
from app.graph.types import GraphDeps

logger = logging.getLogger(__name__)


def _asks_to_explore(normalized_message: str) -> bool:
    return any(
        phrase in normalized_message
        for phrase in (
            "du an khac",
            "cong ty khac",
            "nha may khac",
            "viec khac",
            "xem tat ca",
            "tat ca du an",
            "quay lai tim viec",
        )
    )


def _is_general_or_comparative(normalized_message: str) -> bool:
    """True when a question is factory-agnostic and comparative/general.

    Such questions must NOT be answered from one (focused) project's KB: a salary
    threshold hypothetical ("lam 20 trieu duoc ko"), a superlative ("luong cao
    nhat"), or an explicit multi-factory scope ("nha may nao", "bao nhieu nha
    may"). A bare "luong bao nhieu" is a focused follow-up and returns False, so
    an established focus is preserved for ordinary project-scoped questions.
    """
    text = normalized_message or ""
    if any(
        phrase in text
        for phrase in (
            # Comparative / superlative (inherently cross-project).
            "cao nhat",
            "thap nhat",
            "nhieu nhat",
            "it nhat",
            "tot nhat",
            "gan nhat",
            "moi nhat",
            "xa nhat",
            "so sanh",
            # Explicit multi-factory scope / "which job" browsing.
            "nha may nao",
            "bao nhieu nha may",
            "co bao nhieu nha may",
            "viec lam nao",
            "viec nao",
            "du an nao",
            "cac nha may",
            "cac du an",
            "tat ca nha may",
        )
    ):
        return True
    if is_salary_profile_statement(text):
        return False
    _minimum, target = parse_salary_band(text)
    if target is None:
        return False
    if "luong" in text or "thu nhap" in text:
        return True
    tokens = set(text.split())
    return "lam" in tokens and bool(tokens & {"duoc", "dc"})


class _DirectContextAdapter:
    def __init__(self, db) -> None:
        self._db = db

    async def resolve(self, conversation, user_text: str):
        import re

        from sqlalchemy import select

        from app.shared.domain.text import normalize_vietnamese_text
        from app.graph.direct_context import DirectContext, ProjectTurnContext
        from app.recruitment.domain.provider import provider_from_conversation
        from app.graph.prompts import AGENT_SYSTEM_PROMPT
        from app.models.company import Project
        from app.models.conversation import ConversationProjectState
        from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
        from app.services.knowledge_base_capacity import require_direct_context_ready
        from app.services.personas.repository import PersonaRepository

        rows = (
            await self._db.execute(
                select(Project, KnowledgeBase, KnowledgeBaseDirectFile)
                .join(KnowledgeBase, Project.knowledge_base_id == KnowledgeBase.id)
                .outerjoin(
                    KnowledgeBaseDirectFile,
                    KnowledgeBaseDirectFile.knowledge_base_id == KnowledgeBase.id,
                )
                .where(Project.is_active.is_(True))
                .order_by(Project.name, Project.id)
            )
        ).all()
        normalized_message = normalize_vietnamese_text(user_text)
        matches = []
        for row in rows:
            project = row[0]
            names = [project.slug, project.name, *(project.aliases or [])]
            if any(
                re.search(
                    rf"(?<!\w){re.escape(normalize_vietnamese_text(name))}(?!\w)",
                    normalized_message,
                )
                for name in names
                if len(normalize_vietnamese_text(name)) >= 2
            ):
                matches.append(row)
        if len(matches) > 1:
            names = ", ".join(row[0].name for row in matches)
            return ProjectTurnContext(
                state="EXPLORE",
                clarification=f"Bạn đang muốn hỏi dự án nào: {names}?",
            )

        selected = matches[0] if matches else None
        focused_id = getattr(conversation, "focused_project_id", None)
        if selected is None and _asks_to_explore(normalized_message):
            conversation.project_context_state = ConversationProjectState.EXPLORE
            conversation.focused_project_id = None
            await self._db.commit()
            return ProjectTurnContext(state="EXPLORE")
        if (
            selected is None
            and _is_general_or_comparative(normalized_message)
            and len(rows) >= 2
        ):
            # Factory-agnostic comparative/general question (e.g. a salary
            # threshold "lam 20 trieu duoc ko", "luong cao nhat", "nha may nao").
            # Must NOT be silently answered from one focused project's KB: that
            # is how the bot gave LG Display's "can't confirm 20M" as a universal
            # answer while another factory's KB said 20M is reachable. Keep
            # focused_project_id intact (the user may still be on that thread)
            # but do not pin this turn, so the agent can answer across active
            # projects and ask which one the candidate means.
            return ProjectTurnContext(state="EXPLORE")
        if selected is None and focused_id is not None:
            selected = next((row for row in rows if row[0].id == focused_id), None)
        if selected is None:
            if focused_id is not None or getattr(
                conversation, "project_context_state", "EXPLORE"
            ) != ConversationProjectState.EXPLORE:
                conversation.project_context_state = ConversationProjectState.EXPLORE
                conversation.focused_project_id = None
                await self._db.commit()
            return ProjectTurnContext(state="EXPLORE")

        project, knowledge_base, direct_file = selected
        if focused_id != project.id or getattr(
            conversation, "project_context_state", "EXPLORE"
        ) != ConversationProjectState.FOCUSED:
            conversation.project_context_state = ConversationProjectState.FOCUSED
            conversation.focused_project_id = project.id
            await self._db.commit()

        direct_context = None
        if knowledge_base.mode is KnowledgeBaseMode.DIRECT_CONTEXT:
            provider = provider_from_conversation(conversation)
            persona_body = (
                await PersonaRepository(self._db).active_persona_body(provider)
            ) or AGENT_SYSTEM_PROMPT
            if direct_file is None:
                direct_context = DirectContext(
                    knowledge_base_id=str(knowledge_base.id),
                    persona_body=persona_body,
                    knowledge_text="",
                )
            else:
                await require_direct_context_ready(
                    self._db,
                    knowledge_base,
                    agent_markdown=persona_body,
                )
                direct_context = DirectContext(
                    knowledge_base_id=str(knowledge_base.id),
                    persona_body=persona_body,
                    knowledge_text=direct_file.normalized_text,
                )
        return ProjectTurnContext(
            state="FOCUSED",
            project_id=str(project.id),
            project_slug=project.slug,
            project_name=project.name,
            knowledge_mode=knowledge_base.mode.value,
            direct_context=direct_context,
        )


class _FaqBypassAdapter:
    """FaqBypassPort backed by RetrievalRepository + the shared cached embedder.

    Defined in the composition root so the graph layer imports no concrete
    service module (all ``app.services`` imports are function-level, satisfying
    the AST import-guard). Runs the deterministic cascade from
    :mod:`app.services.retrieval.faq_bypass` and logs every decision so the
    thresholds can be tuned from production logs. Never raises — any failure
    abstains so the turn falls through to the agent unchanged.
    """

    def __init__(self, db, embedder, *, page_project_ids=None) -> None:
        self._db = db
        self._embedder = embedder
        self._page_project_ids = page_project_ids

    async def try_answer(self, user_text: str):
        from app.core.vector import vec_literal
        from app.graph.ports import FaqBypassResult
        from app.graph.tools import _cached_embed
        from app.services.retrieval import RetrievalRepository
        from app.services.retrieval import faq_bypass as fb

        started = time.perf_counter()
        repo = RetrievalRepository(self._db, page_project_ids=self._page_project_ids)
        try:
            active_project_ids = getattr(repo, "active_project_ids", None)
            project_ids = await active_project_ids() if active_project_ids is not None else None
            if project_ids == []:
                return None
            emb = vec_literal(await _cached_embed(self._embedder, user_text))
            # Scope follows active_project_ids: the deployment-wide catalog for
            # Zalo, or the Page's assigned Projects when the turn arrived on a
            # scoped Facebook Page. Both arms must carry it — an unscoped FAQ
            # arm answers from another Page's catalog before retrieval runs.
            faq_scope = {"project_ids": project_ids} if project_ids is not None else {}
            vector_rows = await repo.match_faq(
                emb, top_k=fb.TOP_K, floor=fb.CANDIDATE_VECTOR_FLOOR, **faq_scope
            )
            lexical_rows = await repo.match_faq_lexical(
                user_text, top_k=fb.TOP_K, threshold=fb.TRIGRAM_THRESHOLD, **faq_scope
            )
        except Exception:  # noqa: BLE001 — bypass must never break a turn
            logger.warning("faq_bypass retrieval failed; abstaining", exc_info=True)
            return None

        candidates = list(vector_rows) + list(lexical_rows)
        exact_map = fb.build_exact_map(candidates)
        scored = fb.rerank(list(vector_rows), list(lexical_rows))
        decision = fb.decide(user_text, exact_map, scored)
        latency_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "faq_bypass decision=%s tier=%s score=%.3f top2=%.3f margin=%.3f "
            "vec=%.3f tri=%.3f reason=%s latency_ms=%.1f faq_id=%s",
            decision.decision,
            decision.tier,
            decision.top1_score,
            decision.top2_score,
            decision.margin,
            decision.scored.vec_sim if decision.scored else 0.0,
            decision.scored.tri_sim if decision.scored else 0.0,
            decision.reason,
            latency_ms,
            decision.scored.faq_id if decision.scored else None,
        )
        if decision.decision == fb.DECISION_ACCEPT and decision.scored and decision.scored.answer:
            return FaqBypassResult(
                answer=decision.scored.answer,
                faq_id=decision.scored.faq_id,
                tier=decision.tier,
                score=decision.top1_score,
                reason=decision.reason,
                latency_ms=latency_ms,
                runner_up_score=decision.top2_score if decision.top2_score > 0 else None,
            )
        return None


class _RuntimePolicyAdapter:
    """Installation-backed policy adapter owned by the graph composition root."""

    def __init__(self, db) -> None:
        self._db = db

    async def resolve_active_policy(self):
        from app.graph.runtime_policy import build_resolved_runtime_policy
        from app.shared.domain.errors import InstallationError
        from app.services.installation.service import InstallationService

        installation = InstallationService(self._db)
        try:
            active = await installation.require_active()
        except InstallationError:
            return None
        persona = await installation.repo.get_persona_version(active.revision.persona_version_id)
        return build_resolved_runtime_policy(
            active,
            persona_body=persona.body_md if persona is not None else None,
        )

    async def runtime_stamp_is_current(
        self, *, revision_id: str, authority_generation: int, runtime_fingerprint: str
    ) -> bool:
        from app.services.installation.authority import RuntimeAuthorityStamp
        from app.services.installation.service import InstallationService

        try:
            return await InstallationService(self._db).runtime_stamp_is_current(
                RuntimeAuthorityStamp(
                    revision_id=uuid.UUID(revision_id),
                    authority_generation=authority_generation,
                    fingerprint=runtime_fingerprint,
                )
            )
        except (ValueError, TypeError):
            return False


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


def _build_fast_llm(*, minimax_config, openrouter_config):
    """Build the optional fast-tier LLM for low-complexity intents (Phase 5).

    Returns ``None`` when no fast model is configured on the active provider —
    ``MiniMaxAgent`` then no-ops the ``use_fast`` switch (every turn uses the
    primary reasoning model, the pre-tiering default).

    The fast model is built directly (not via ``_chat_for_role``) because the
    role factory hard-codes the agent/safety model names. Here we explicitly use
    ``minimax_fast_model`` / ``openrouter_fast_model`` so the tier is genuine.

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
        return None
    except Exception:  # noqa: BLE001
        logger.warning("fast-tier LLM build failed; primary-only tier", exc_info=True)
        return None


def _build_failover_chain(*, minimax_config, openrouter_config, custom_config):
    """Clients for every configured provider EXCEPT the active one, in order.

    The operator does not nominate a spare: any provider they have enabled with
    a usable credential is eligible, so enabling OpenRouter alongside MiniMax is
    enough to survive a spent MiniMax plan. Order is deterministic — the other
    first-class provider, then the generic OpenAI-compatible slot — so failover
    behaviour is predictable rather than dependent on dict ordering.

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

    if active != "minimax" and minimax_config.enabled and minimax_config.api_key:
        _add(
            "minimax",
            # DB-managed model id wins over the env default, matching how the
            # active provider resolves its model.
            lambda: _minimax_chat(
                minimax_config.agent_model or s.minimax_agent_model,
                temperature=0.3,
                api_key=minimax_config.api_key,
            ),
        )
    if active != "openrouter" and openrouter_config.enabled and openrouter_config.api_key:
        _add(
            "openrouter",
            lambda: _openrouter_chat(
                openrouter_config.agent_model,
                temperature=0.3,
                timeout=s.openrouter_request_timeout,
                api_key=openrouter_config.api_key,
                capture_reasoning=True,
            ),
        )
    if active != "custom" and custom_config is not None and custom_config.usable:
        _add(
            "fallback",
            lambda: _custom_chat(
                custom_config.agent_model,
                temperature=0.3,
                api_key=custom_config.api_key,
                base_url=custom_config.base_url,
            ),
        )
    return chain


# ── Process-wide LLM client cache ───────────────────────────────────────────
# The ChatOpenAI clients + embedder are expensive to construct (langchain_openai
# import + httpx/pydantic wiring). Caching them avoids rebuilding on every turn.
# Keyed by the minimax + openrouter integration-settings cache versions ONLY —
# the two providers whose settings actually drive agent_llm / embedder / fast_llm
# construction. Zalo is deliberately excluded: its config feeds the per-turn
# ZaloChannelSender (resolved fresh in build_deps), so an OA token rotation
# invalidating this cache would force a needless 5-7s LLM-client rebuild.
#
# Scope of the win:
# - Direct/ASGI path (start_direct_chat_turn): multiple turns share one event
#   loop + one _client_cache in the web process → the 2nd+ turn skips rebuild.
# - RQ fork-per-job path: each forked child starts with an empty cache (the
#   parent's cache cannot be inherited — ChatOpenAI wraps an httpx pool whose
#   sockets must not be shared across fork()). So under default RQ each child
#   builds once and exits; the per-turn win there is the asyncio.gather over
#   the resolve_* calls, not this cache. Moving chatbot turns off fork-per-job
#   (SimpleWorker) is what makes this cache bite on the worker path.
#
# ``_build_cached_clients`` is the single constructor; ``build_deps`` reads the
# cache and only re-binds the per-turn pieces (db session, retrieval repo, lead
# adapter, faq_bypass adapter, zalo config + sender with its refresh closure,
# followup gate).


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


async def _build_cached_clients(db) -> _CachedClients:  # noqa: RUF029 (async for lock)
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
        )
        failover_llms = _build_failover_chain(
            minimax_config=minimax_config,
            openrouter_config=openrouter_config,
            custom_config=custom_config,
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
        faq_bypass=_FaqBypassAdapter(db, clients.embedder, page_project_ids=page_project_ids),
        followup_allowed=_make_followup_allowed(db),
        enrich_oa_profile=_enrich_oa_profile,
        runtime_policy=_RuntimePolicyAdapter(db),
        direct_context=_DirectContextAdapter(db),
        proactive_state=_build_proactive_state(db),
        delivery_statuses=_build_delivery_statuses(),
    )


def _make_followup_allowed(db):
    from app.composition.recruitment import build_followup_eligibility

    adapter = build_followup_eligibility(db)
    return adapter.allowed


def _build_lead_context(db):
    from app.composition.recruitment import build_lead_context

    return build_lead_context(db)


def _build_proactive_state(db):
    from app.composition.recruitment import build_proactive_state

    return build_proactive_state(db)


def _build_delivery_statuses():
    from app.composition.conversation_messaging import build_delivery_status_values

    return build_delivery_status_values()
