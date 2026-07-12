---
title: "Zalo candidate avatars — full-stack feature from zero"
date: "2026-07-12"
status: implemented
scope: "backend (zalo_oa_service, profile_enrichment, persistence_worker, webhook, lead model/schema/repository, alembic), frontend (LeadAvatar, ConversationList/Show/ChatThread, types)"
---

# Zalo candidate avatars — full-stack feature from zero

## Context

The recruiter console rendered only placeholder icons/initials for every
candidate because the avatar data was never fetched, stored, or rendered — a
six-layer gap spanning the entire stack. A pre-existing plan
(`plans/20260712-zalo-candidate-avatars/`) specified the approach; this entry
records the implementation + two issues caught by the code-reviewer.

## What was built

**Backend (Phase 1+2):**
- `ZaloOASender.get_user_detail()` — calls `GET /v3.0/oa/user/detail` with
  URL-encoded compact JSON `data` param, refresh-aware (one retry on stale
  token). Parses `avatars.240` > `avatar` > `avatars.120` priority.
- `ProfileEnrichmentService` — best-effort lookup + persist. Short-circuits
  when the lead already has avatar+name (no unbounded Zalo calls). Uses a
  scoped `_ENRICH_SQL` UPDATE that only patches avatar + missing name.
- Enrichment wired into the OA webhook as a fire-and-forget `persistence_low`
  job — never blocks the sub-second webhook ack.
- Migration `0035_lead_avatar_url` (additive nullable text column).
- `LeadOut.avatar_url` (additive nullable). `_FETCH_SQL` includes it; `_UPSQL`
  deliberately does NOT (LLM extraction must never clobber an enriched avatar).

**Frontend (Phase 3):**
- `LeadAvatar` — reusable component: renders `<img>` when avatar_url present,
  falls back to `UserRound` icon. Used across inbox rows, chat header, and
  chat-thread message avatars.

## What the code-reviewer caught (and I fixed)

1. **Critical — broken-image fallback was invisible.** The `onError` handler
   hid the `<img>` but the icon underneath stayed `visibility: hidden`
   (computed from `src` at render time, not updated on error). Fixed by lifting
   to `useState(imgFailed)` + extracting `resolveAvatarSrc()` so the icon
   branch re-derives on failure. Zalo doesn't document avatar URL lifetime, so
   404/expired URLs are an expected production path — the fallback must work.

2. **High — enriched avatar never refreshed in an open conversation.** The
   enrichment committed via raw SQL but didn't emit `lead.updated`, so the
   realtime `refetchLead()` listener in `ConversationShow` never fired. Fixed
   by emitting `LeadEventBus().lead_updated(saved)` after commit, mirroring
   `candidate_extraction.upsert_lead`. Wrapped in try/except so a realtime
   outage never fails the commit.

Plus: webhook enrichment enqueue integration test (H2), phantom test replaced
with real logic test (M1), inline imports moved to module scope (M2), worker
log level aligned to `warning` (M4).

## Key decision: avatar_url excluded from _UPSQL

The LLM extraction upsert (`_UPSQL`) runs on every candidate extraction pass.
If it included `avatar_url`, a subsequent extraction (which never produces an
avatar) would pass `NULL` and — even with COALESCE — risk edge cases. By
keeping `avatar_url` out of `_UPSQL` entirely and making `_ENRICH_SQL` the
sole writer, the separation is clean: extraction owns profile fields,
enrichment owns the avatar. An enriched avatar survives any number of later
extraction runs.

## Operational prerequisite

The connected OA application must have Zalo's user-information management
permission. Without it, enrichment fails soft (logs, no crash) and the UI
keeps the initials fallback.
