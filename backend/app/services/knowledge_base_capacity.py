"""Direct-context knowledge capacity checks for the active answer model.

Direct-context KBs deliberately send their sole text file on every answer.  They
must therefore fit alongside the Agent instructions, retained chat history and
the reserved answer budget.  Every chatbot agent lane — MiniMax, OpenRouter or
the operator-supplied endpoint — runs on the same 1M-token window, so capacity
is one deployment constant rather than a per-provider lookup.  RAG KBs do not
use this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
from app.shared.domain.errors import ConflictError
from app.services.integration_settings import IntegrationSettingsService

# Every chatbot agent (agent/safety/fast lanes, on any provider) answers inside a
# 1M-token context window.  The window is a property of the deployment, not an
# operator setting: a stored "custom_llm_context_window" row is inert and the
# settings UI exposes no context-window field.  Deliberately NOT a per-model
# registry — the old MiniMax/OpenRouter lookups went stale on every vendor
# release (an unregistered model name made every direct-context KB unusable) and
# an 8s metadata call could fail a KB assignment.

# A deliberately conservative Vietnamese/text estimate.  The provider tokenizer
# remains authoritative at request time, so capacity is validated with headroom.
_CHARS_PER_ESTIMATED_TOKEN = 2
_CHATBOT_CONTEXT_WINDOW_TOKENS = 1_024_000
_BASE_SYSTEM_RESERVE_TOKENS = 6_000
_CHAT_HISTORY_RESERVE_TOKENS = 12_000
_CURRENT_MESSAGE_RESERVE_TOKENS = 2_000
_OUTPUT_RESERVE_TOKENS = 4_000


@dataclass(frozen=True)
class DirectContextCapacity:
    provider: str
    model: str
    context_window_tokens: int
    reserved_tokens: int
    estimated_input_tokens: int

    @property
    def available_input_tokens(self) -> int:
        return self.context_window_tokens - self.reserved_tokens

    @property
    def fits(self) -> bool:
        return self.estimated_input_tokens <= self.available_input_tokens


def _estimate_tokens(text: str) -> int:
    return ceil(len(text) / _CHARS_PER_ESTIMATED_TOKEN)


async def _active_model_context(db: AsyncSession) -> tuple[str, str, int]:
    """Return the active provider, its agent model, and the chatbot's window.

    The window is the same 1M constant for every provider, so this resolves only
    *which* model is answering; it cannot fail on an unknown model name, a vendor
    registry miss, or a metadata HTTP call.
    """
    settings = IntegrationSettingsService(db)
    minimax = await settings.resolve_minimax()
    provider = minimax.default_provider
    if provider == "custom":
        model = (await settings.resolve_custom_llm()).agent_model
    elif provider == "openrouter":
        model = (await settings.resolve_openrouter()).agent_model
    else:
        model = minimax.agent_model
    return provider, model, _CHATBOT_CONTEXT_WINDOW_TOKENS


async def direct_context_capacity(
    db: AsyncSession,
    direct_file: KnowledgeBaseDirectFile,
    *,
    agent_markdown: str = "",
) -> DirectContextCapacity:
    provider, model, context_window = await _active_model_context(db)
    reserved = (
        _BASE_SYSTEM_RESERVE_TOKENS
        + _CHAT_HISTORY_RESERVE_TOKENS
        + _CURRENT_MESSAGE_RESERVE_TOKENS
        + _OUTPUT_RESERVE_TOKENS
        + _estimate_tokens(agent_markdown)
    )
    return DirectContextCapacity(
        provider=provider,
        model=model,
        context_window_tokens=context_window,
        reserved_tokens=reserved,
        estimated_input_tokens=_estimate_tokens(direct_file.normalized_text),
    )


async def ensure_direct_context_fits(
    db: AsyncSession,
    direct_file: KnowledgeBaseDirectFile,
    *,
    agent_markdown: str = "",
) -> DirectContextCapacity:
    """Prove an already-fetched direct file fits the active answer model.

    Per-turn callers fetch the file once — it is the system prompt text anyway —
    and pass it here, so the capacity guard adds no extra SELECT and no second
    transfer of the full text row. The token estimate itself is an O(1) ``len()``
    on the in-hand text (see :func:`_estimate_tokens`).
    """
    capacity = await direct_context_capacity(db, direct_file, agent_markdown=agent_markdown)
    if not capacity.fits:
        raise ConflictError(
            "The direct-context file does not fit the active model after conversation and answer reserves"
        )
    return capacity


async def require_direct_context_ready(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    agent_markdown: str = "",
) -> DirectContextCapacity | None:
    """Return RAG unchanged, or prove that a direct KB can answer safely."""
    if knowledge_base.mode is KnowledgeBaseMode.RAG:
        return None
    direct_file = await db.scalar(
        select(KnowledgeBaseDirectFile).where(
            KnowledgeBaseDirectFile.knowledge_base_id == knowledge_base.id
        )
    )
    if direct_file is None:
        raise ConflictError("A direct-context knowledge base needs one text file before use")
    return await ensure_direct_context_fits(db, direct_file, agent_markdown=agent_markdown)
