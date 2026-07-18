---
date: 2026-07-18
session: terse-vacancy-followup-routing
---

# Journal: Terse Vacancy Follow-up Routing

## Context

After the bot introduced a specific vacancy, a candidate could reply with a
short question such as `có việc gì` (including common typing noise such as
`ó viedjc gì`). The catalog detector and turn router disagreed about this
shape, allowing the empty active-job catalog fallback to replace a contextual
answer.

## Decision

Terse job-like questions without an explicit availability or recruiting cue
are ambiguous follow-ups. They remain on the low-confidence, unconstrained LLM
route with conversation history; deterministic routing does not guess their
meaning or force the active-job catalog tool. Explicit catalog questions,
including `bên mình đang tuyển gì?` and `còn công việc nào không?`, retain the
structured `list_active_jobs` authority path.
