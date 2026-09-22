"""Direct-context knowledge capacity checks for the active answer model.

Direct-context KBs deliberately send their sole text file on every answer.  They
must therefore fit alongside the Agent instructions, retained chat history and
the reserved answer budget of the *currently selected* provider/model.  RAG KBs
do not use this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http import get_http_client
from app.models.knowledge import KnowledgeBase, KnowledgeBaseDirectFile, KnowledgeBaseMode
from app.shared.domain.errors import ConflictError
from app.services.integration_settings import IntegrationSettingsService

# The MiniMax API documents a 204,800-token total window for these models.  Keep
# this small registry explicit: an unrecognised model is not assumed to fit.
_MINIMAX_CONTEXT_WINDOWS = {
    "minimax-m2": 204_800,
    "minimax-m2.1": 204_800,
    "minimax-m2.1-highspeed": 204_800,
    "minimax-m2.5": 204_800,
    "minimax-m2.5-highspeed": 204_800,
    "minimax-m2.7": 204_800,
    "minimax-m2.7-highspeed": 204_800,
}

# A deliberately conservative Vietnamese/text estimate.  The provider tokenizer
# remains authoritative at request time, so capacity is validated with headroom.
_CHARS_PER_ESTIMATED_TOKEN = 2
# Conservative fallback for custom (operator-supplied OpenAI-compatible)
# providers: a too-small limit only forces a KB rejection the operator can
# raise in the settings UI; a too-large one admits files that overflow the
# real model window and fail at turn time.
_DEFAULT_CUSTOM_CONTEXT_WINDOW = 32768
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
    settings = IntegrationSettingsService(db)
    minimax = await settings.resolve_minimax()
    if minimax.default_provider == "minimax":
        model = minimax.agent_model
        context_window = _MINIMAX_CONTEXT_WINDOWS.get(model.strip().lower())
        if context_window is None:
            raise ConflictError(
                f"No context-window limit is registered for the active MiniMax model '{model}'"
            )
        return "minimax", model, context_window

    if minimax.default_provider == "custom":
        custom = await settings.resolve_custom_llm()
        model = custom.agent_model
        # Operators supply the window for their own endpoint; the default is
        # deliberately conservative — a too-small limit only forces a KB
        # rejection, a too-large one admits files that overflow the real
        # window and fail at turn time.
        context_window = custom.context_window or _DEFAULT_CUSTOM_CONTEXT_WINDOW
        return "custom", model, context_window

    raise ConflictError("The active LLM provider has no direct-context capacity resolver")

    openrouter = await settings.resolve_openrouter()
    model = openrouter.agent_model
    client = await get_http_client(
        "openrouter_model_metadata",
        base_url=openrouter.base_url.rstrip("/"),
    )
    headers = {"Authorization": f"Bearer {openrouter.api_key}"} if openrouter.api_key else None
    try:
        response = await client.get(
            f"models/{quote(model, safe='/')}", headers=headers, timeout=8.0
        )
        response.raise_for_status()
        payload = response.json()
        context_window = payload.get("context_length")
        if not isinstance(context_window, int) or context_window <= 0:
            raise ValueError("missing context_length")
    except Exception as exc:  # noqa: BLE001 - configuration cannot safely guess a limit
        raise ConflictError(
            f"Could not resolve the context window for active OpenRouter model '{model}'"
        ) from exc
    return "openrouter", model, context_window


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
    capacity = await direct_context_capacity(db, direct_file, agent_markdown=agent_markdown)
    if not capacity.fits:
        raise ConflictError(
            "The direct-context file does not fit the active model after conversation and answer reserves"
        )
    return capacity
