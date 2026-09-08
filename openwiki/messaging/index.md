# Files

- [Conversation lifecycle, ownership, and delivery state](conversation-lifecycle.md) - Conversation persistence model, per-conversation DB lock + owner token + TTL, delivery-state machine, recruiter-driven transitions (take_over / release / semi_auto / close / reopen), and the outbound dispatcher tick that recovers stale commands.
- [Realtime push (Socket.IO server, cross-process bridge, console)](realtime-socketio.md) - How the recruiter console subscribes to per-conversation rooms via Socket.IO, how FastAPI publishes through a cross-process Redis-backed emit bridge from any process, and the room naming + presence/typing semantics.
