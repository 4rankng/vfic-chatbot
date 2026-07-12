---
title: "Messaging hardening — one real bug, three instrumentation adds, five rejected"
date: "2026-07-12"
status: completed
scope: "backend/app/graph/send_classification.py, app/graph/runner.py, alembic 0030–0032, performance endpoint, semantic-FAQ abstain"
---

# Messaging hardening — one real bug, three instrumentation adds, five rejected

Adapted an external enterprise-messaging architecture review against the actual
codebase. The review proposed 7 improvements. After verifying each claim against
source, 5 were rejected as over-built for a 2 vCPU single-tenant droplet
(transactional outbox, 14-state turn machine, generation/delivery worker split,
per-tool idempotency journal, …) and one was factually wrong — it claimed LLM
tools mutate state, but all 7 tools are read-only retrievals. Only 4 survived:
one real bug fix plus three instrumentation additions.

## The one real bug: SEND_UNKNOWN

When the Zalo HTTP POST raises a transport timeout AFTER the request may have
reached Zalo, the message was marked FAILED → the reconciler re-enqueued it →
the candidate got two replies. Fix: a conservative transport-error classifier
(`backend/app/graph/send_classification.py`), a `SEND_UNKNOWN` enum value
(migration 0030), and ambiguous sends are now non-retriable. Applied to the
runner send path, the degradation path, and `_finish_terminal_reply`.

## The architecture guard caught a cycle immediately

First cut imported `AMBIGUOUS_SEND_CLASSES` from `app.services.zalo_bot_service`
into `app.graph.runner`. `backend/tests/test_graph_import_guard.py` (an AST
guard) failed on the next test run — graph must not depend on services. Fixed
by placing the classifier in `app/graph/send_classification.py` as a leaf
utility. Reusable lesson: the graph↔services boundary is enforced by tests, and
constants shared across the boundary must live in the graph layer.

## The brutal truth

Two things hurt here. First, the code reviewer found a real correctness bug I
would have shipped: the reconciler's SEND_UNKNOWN skip branch was dead code
because the candidate SQL filtered to `IN ('PENDING','SENDING','FAILED')` —
SEND_UNKNOWN never reached the skip. I had built an inert observability counter
and called the phase done. Embarrassing. Second, while I was implementing
Phase 3, a concurrent process refactored `app/api/performance.py` underneath me
— Redis caching, `asyncio.gather` concurrent reads, rewritten test file. I ran
tests, the file was unrecognizable from what I had just edited. Genuinely
disorienting. The plan had flagged this coordination risk explicitly; that
flag is the only reason I didn't lose an hour assuming I was losing my mind.

The most satisfying part was the YAGNI triage. Saying "no" to 5 of 7
recommendations with verified evidence — reading the actual tool
implementations to disprove the state-mutation claim — beats pattern-matching
on enterprise architecture bingo every time. Enterprise patterns are written
for enterprises.

## Bot behavior change worth flagging

Phase 4 changed candidate-facing behavior: low-margin semantic-FAQ matches
(`runner_up_score` within `faq_abstain_margin: float = 0.03`) now abstain to
the LLM instead of trusting a potentially-wrong FAQ answer. Candidates who
previously got a FAQ answer will now get an LLM reply on low-margin matches.
This is intentional, but it is a behavior change, not just instrumentation.

## Verification

- Backend: 685 passed, 10 skipped, 0 new failures.
- Frontend: tsc strict clean, ESLint clean. Ruff clean on all changed files.
- Code review's 4 issues (C1 dead reconciler branch, H1 unprotected error path,
  M1 required-frontend crash risk, M3 contextvar token leak) all fixed.

## Next

- Treat `send_classification.py` as the canonical home for transport-error
  classification; do not re-inline these constants into services.
- Watch the FAQ-abstain behavior change after deploy — confirm LLM fallback
  fires on low-margin matches and answer quality holds.
- When the next "enterprise messaging" review lands, default to YAGNI triage
  with source verification, not pattern adoption.
