"""Conversation lifecycle service package (repository + state + events).

Public API: ``ConversationService`` (a facade composing a repository, an event bus, and
a state machine) + ``ConversationConflict``; importers should depend on
``app.services.conversation`` rather than the internal submodules.

The facade composes named parts; callers that know which part they mean reach
for it directly (``svc.state.take_over``, ``svc.repo.list``) instead of through
the facade. Only the graph port's surface and the cross-part orchestrations
stay on the class itself.
"""

from app.services.conversation.service import ConversationService
from app.services.conversation.state import ConversationConflict

__all__ = ["ConversationConflict", "ConversationService"]
