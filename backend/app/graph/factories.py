"""Dependency factories for the graph's LLM/embedder wiring.

- ``build_deps`` wires the full ``GraphDeps`` for the chatbot worker.
- ``build_minimax_extractor`` — candidate extraction (persistence worker).
- ``make_minimax_llm_json`` — JSON-mode LLM for the knowledge training pipeline (ingest worker).

langchain_openai is imported lazily inside each factory so the web-process import path
stays langchain-free.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.graph.clients import MiniMaxAgent, MiniMaxSafety, _chat_for_role, build_embedder
from app.graph.types import GraphDeps

logger = logging.getLogger(__name__)


class _LeadContextAdapter:
    """LeadContextPort backed by the concrete lead service pieces.

    Defined here (the composition root) so the graph layer never imports the lead
    service modules. Each method does one DB fetch, matching the prior single-fetch
    behavior of the brain; the caller owns the best-effort try/except.
    """

    def __init__(self, db) -> None:
        self._db = db

    async def profile_text(self, chat_id: str) -> str:
        from app.services.lead import lead_profile_text
        from app.services.lead.repository import LeadRepository

        lead = await LeadRepository(self._db).by_zalo_id(chat_id)
        return lead_profile_text(lead)

    async def context(self, chat_id, current_user_text, recent_messages):
        from app.services.lead import lead_profile_text
        from app.services.lead.probing import lead_collection_question
        from app.services.lead.repository import LeadRepository

        lead = await LeadRepository(self._db).by_zalo_id(chat_id)
        return (
            lead_profile_text(lead),
            lead_collection_question(
                lead=lead,
                current_user_text=current_user_text,
                recent_messages=recent_messages,
            ),
        )

    def instruction(self, question: str) -> str:
        from app.services.lead.probing import lead_collection_instruction

        return lead_collection_instruction(question=question)

    def ensure(self, reply: str, question: str) -> str:
        from app.services.lead.probing import ensure_lead_collection_question

        return ensure_lead_collection_question(reply, question)


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


async def build_deps(db):
    """Wire the full GraphDeps for one chatbot turn (agent + safety + embedder + zalo)."""
    from app.services.conversation import ConversationService
    from app.services.integration_settings import IntegrationSettingsService
    from app.services.zalo_sender import ZaloChannelSender

    s = get_settings()
    integration_settings = IntegrationSettingsService(db, settings=s)
    minimax_config = await integration_settings.resolve_minimax()
    openrouter_config = await integration_settings.resolve_openrouter()
    agent_llm = _chat_for_role(
        "agent",
        temperature=0.3,
        minimax_api_key=minimax_config.api_key,
        openrouter_api_key=openrouter_config.api_key,
    )
    safety_llm = _chat_for_role(
        "safety",
        temperature=0.0,
        minimax_api_key=minimax_config.api_key,
        openrouter_api_key=openrouter_config.api_key,
    )
    embedder = build_embedder(s, openrouter_api_key=openrouter_config.api_key)
    zalo_config = await integration_settings.resolve_zalo()
    return GraphDeps(
        db=db,
        agent=MiniMaxAgent(agent_llm, embedder),
        safety=MiniMaxSafety(safety_llm),
        embedder=embedder,
        zalo=ZaloChannelSender(
            zalo_config,
            refresh=lambda: integration_settings.refresh_oa_access_token(),
        ),
        conversation=ConversationService(db),
        lead=_LeadContextAdapter(db),
        followup_allowed=_make_followup_allowed(db),
    )


def _make_followup_allowed(db):
    from app.services.proactive.repository import conversation_allowed_by_followup_rules

    async def _allowed(conv):
        return await conversation_allowed_by_followup_rules(db, conv)

    return _allowed
