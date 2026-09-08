# Files

- [Decision trace, audit log, and bot_runs resource](decision-trace.md) - How every bot execution is recorded (allowlisted control-flow events only), how audit is appended, how decision traces are bounded and pruned, and how the bot_runs API surfaces them to recruiters.
- [Bot-turn pipeline (LangGraph runtime)](pipeline.md) - Per-turn pipeline node order (load → typing → agent → safety → pre-send guard → send), how the graph brain depends on Ports and GraphDeps, how factories wire concrete services, and the conversation lock that enforces at-most-one in-flight turn.
- [Safety filter chain and turn routing](safety-and-routing.md) - Deterministic fast safety filter, LLM safety judge, retry-rewrite cap, grounding cross-check, pre-send claim fence, and the routing intents that drive model tier selection.
