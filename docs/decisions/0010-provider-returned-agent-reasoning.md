# ADR-0010: Preserve provider-returned agent reasoning

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decider:** Product owner

## Context

The recruiting agent can invoke an LLM several times in one bot turn, with tool calls between
invocations. Administrators need to inspect the reasoning returned by the provider and the tools
selected in each invocation. MiniMax returns reasoning in `<think>` blocks, while OpenRouter may
return `reasoning`, `reasoning_content`, or `reasoning_details`. The generic OpenAI-compatible
LangChain adapter does not preserve all third-party reasoning fields across tool rounds.

## Decision

Use a small OpenAI-compatible chat adapter that preserves provider reasoning fields on assistant
messages and forwards them unchanged in subsequent tool-loop requests. After every provider
invocation, record one bounded version-2 `model_turn` event containing provider/model identity,
phase, returned/not-returned/truncated status, returned reasoning text, and allowlisted selected tool
names. Version 2 contains no route, policy, prefetch, candidate-answer, tool-argument, tool-result,
or evidence fields. Legacy version-1 execution traces remain parseable but are not displayed as
Agent Thinking.

Reasoning is sensitive free-form data because a provider may echo conversation context within it.
Trace access is admin-only, detail is loaded on demand, each reasoning block is capped at 16 KiB,
the full trace at 128 KiB and 64 events, and trace JSON expires after 30 days.

## Consequences

- **Positive:** Admins can follow multi-invocation reasoning and tool selection in the exact order
  returned by supported providers.
- **Positive:** OpenRouter interleaved reasoning survives tool rounds instead of being silently
  discarded by the generic adapter.
- **Negative:** Retained reasoning may contain sensitive contextual text and increases `BotRun` row
  size, requiring strict authorization, bounds, and retention.
- **Neutral:** Reasoning not returned by a provider remains unavailable and is shown as
  `not_returned`; the system does not reconstruct it.

## Related

- [`../system-architecture.md`](../system-architecture.md)
- [`../api.md`](../api.md)
