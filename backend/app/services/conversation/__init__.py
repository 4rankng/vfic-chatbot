"""Conversation lifecycle service package (repository + state + events).

Public API: ``ConversationService`` (a facade composing a repository, an event bus, and
a state machine) + ``ConversationConflict``; importers should depend on
``app.services.conversation`` rather than the internal submodules.

NOTE: ``from __future__ import annotations`` is required because this module defines a
method named ``list``, which would otherwise shadow the builtin ``list`` during class-body
annotation evaluation.
"""

from __future__ import annotations

from app.services.conversation.events import ConversationEventBus
from app.services.conversation.repository import ConversationRepository
from app.services.conversation.state import ConversationConflict, ConversationState

__all__ = ["ConversationConflict", "ConversationService"]


class ConversationService:
    """Facade over the conversation read/state/event layers.

    Composes :class:`ConversationRepository` (reads), :class:`ConversationEventBus`
    (realtime publishing), and :class:`ConversationState` (mutations + orchestration),
    then re-exposes the union of their public methods with identical signatures so the
    three consumers (``graph/runner``, ``services/webhook``, ``api/conversations``) need
    no import changes. ``self.db`` is preserved for callers that refresh the session
    directly (e.g. ``graph/runner.run_turn``).
    """

    def __init__(self, db) -> None:
        self.db = db
        self.repo = ConversationRepository(db)
        self.events = ConversationEventBus(db)
        self.state = ConversationState(db, self.repo, self.events)

    # --- reads (delegate to repository) ---
    async def get(self, *args, **kwargs):
        return await self.repo.get(*args, **kwargs)

    async def get_by_zalo(self, *args, **kwargs):
        return await self.repo.get_by_zalo(*args, **kwargs)

    async def last_messages_batch(self, *args, **kwargs):
        return await self.repo.last_messages_batch(*args, **kwargs)

    async def list(self, *args, **kwargs):
        return await self.repo.list(*args, **kwargs)

    async def needs_attention_count(self, *args, **kwargs):
        return await self.repo.needs_attention_count(*args, **kwargs)

    async def last_messages(self, *args, **kwargs):
        return await self.repo.last_messages(*args, **kwargs)

    async def messages_page(self, *args, **kwargs):
        return await self.repo.messages_page(*args, **kwargs)

    # --- mutations (delegate to state) ---
    async def ensure(self, *args, **kwargs):
        return await self.state.ensure(*args, **kwargs)

    def run_start_guard(self, *args, **kwargs):
        return self.state.run_start_guard(*args, **kwargs)

    def semi_auto_inactive(self, *args, **kwargs):
        return self.state.semi_auto_inactive(*args, **kwargs)

    async def record_inbound(self, *args, **kwargs):
        return await self.state.record_inbound(*args, **kwargs)

    async def acquire_lock(self, *args, **kwargs):
        return await self.state.acquire_lock(*args, **kwargs)

    async def release_lock(self, *args, **kwargs):
        return await self.state.release_lock(*args, **kwargs)

    async def recheck_ownership(self, *args, **kwargs):
        return await self.state.recheck_ownership(*args, **kwargs)

    async def record_bot_outcome(self, *args, **kwargs):
        return await self.state.record_bot_outcome(*args, **kwargs)

    async def take_over(self, *args, **kwargs):
        return await self.state.take_over(*args, **kwargs)

    async def release(self, *args, **kwargs):
        return await self.state.release(*args, **kwargs)

    async def semi_auto(self, *args, **kwargs):
        return await self.state.semi_auto(*args, **kwargs)

    async def close(self, *args, **kwargs):
        return await self.state.close(*args, **kwargs)

    async def reopen(self, *args, **kwargs):
        return await self.state.reopen(*args, **kwargs)

    async def mark_read(self, *args, **kwargs):
        return await self.state.mark_read(*args, **kwargs)

    async def record_recruiter_message(self, *args, **kwargs):
        return await self.state.record_recruiter_message(*args, **kwargs)

    async def record_proactive_outcome(self, *args, **kwargs):
        return await self.state.record_proactive_outcome(*args, **kwargs)

    async def deliver_recruiter_message(self, conv, recruiter, body):
        """Send a recruiter reply via Zalo + record it. Returns ``(message, delivered_ok)``.

        Owns the ``ZaloBotSender`` instantiation so the router stays free of the external
        client. The sender is imported lazily to keep the web-process import path free of
        httpx/external deps at module load. ``record_recruiter_message`` (state) stays a
        decoupled, testable pure-persist that takes the send result as a param.
        """
        from app.services.zalo_bot_service import ZaloBotSender

        result = await ZaloBotSender().send(conv.zalo_chat_id, body)
        msg = await self.state.record_recruiter_message(conv, recruiter, body, result)
        return msg, result.ok
