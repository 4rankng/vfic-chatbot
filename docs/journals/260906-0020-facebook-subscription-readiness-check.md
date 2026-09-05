---
date: 2026-09-06
session: facebook-subscription-readiness-check
---

# Journal: Facebook Messenger webhook-subscription readiness check

## Context

The goal was to prepare the platform to onboard an external customer's
Facebook Page (currently served by Pancake) onto our chatbot. A scoping pass
with the operator settled the boundaries explicitly: one active Page at a
time, no Alembic migration for multi-active-Page, no per-Page Agent override,
no tenant isolation — all deferred. That left an honest question: with the
single-Page pipeline already feature-complete (OAuth connect, webhook ingest,
bot turn, outbox dispatch, receipts, disconnect), what preparation was still
actually missing?

## What Happened

- Scouted the channel layer end to end and found the real gap was not
  plumbing: outbound dispatch already resolves the Page per conversation, and
  tokens are stored per Page with page-bound AEAD. The gap was verification.
- The connection health probe only validated the Page token. It could not
  detect that the app's webhook subscription on the Page had been dropped —
  exactly the failure mode a Pancake cutover risks, and one that silently
  swallows all customer messages.
- Added `page_is_app_subscribed()` (Graph `subscribed_apps` edge, fail-closed,
  `limit=100`) and extended `POST /admin/integrations/facebook/test`:
  `healthy` now requires token validity AND subscription, reporting
  `app_subscribed` with actionable Vietnamese errors.
- Surfaced the subscription confirmation in the Messenger settings page and
  covered subscribed / not-subscribed / lookup-failure paths with tests.
- Wrote `docs/facebook-messenger-onboarding.md`: prerequisites (app Live, App
  Review, business verification), customer-side Pancake removal steps in
  Vietnamese, operator cutover order, verification checklist, rollback.

## The Brutal Truth

The first instinct — build multi-Page support — was wrong, and the operator
corrected it three times in one answer round ("don't rush"). The codebase had
quietly already done most of the work; the remaining valuable change was one
Graph API call that answers "will events actually arrive?" A smaller diff than
planned is not a smaller outcome. Also humbling: a duplicated assert line and
a missing `__all__` entry survived my own sweep and were caught by the
independent reviewer — the review lane earns its keep even on a small diff.

## Technical Details

- One Page stays the V1 model: the partial unique index
  `uq_channel_accounts_one_active_facebook_messenger` is untouched, and
  activating a new Page still archives the previous one.
- The subscription lookup shares the module's redaction discipline: static
  error strings only, provider envelopes never echoed, and tests assert the
  page token never appears in any error.
- An inconclusive lookup (transport/parse failure or unknown app id) reports
  `app_subscribed=None` and unhealthy rather than guessing.
- The pre-existing DB-backed integration suite cannot run locally (no
  integration-test Postgres); the reviewer reproduced identical pre-existing
  collection errors on a stashed clean tree, confirming the gap is
  environmental, not from this change.

## Lessons Learned

- Before building capability, audit what the existing architecture already
  promises — the resolver Protocol explicitly said "never assumes one global
  account", and that sentence redirected the whole task.
- A health probe should test the causal chain it claims to certify (token →
  subscription → events), not just the first link.
- Ask the scope questions before the plan, not after: three one-line answers
  cut the diff from a schema migration + persona model to one provider
  function, one endpoint, tests, and a runbook.
