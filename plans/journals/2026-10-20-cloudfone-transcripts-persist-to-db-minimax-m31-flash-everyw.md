---
title: Cloudfone transcripts persist to DB; MiniMax-M3.1-Flash everywhere
date: 2026-10-20
summary: "Transcribe-once transcript cache (cloudfone_call_transcripts, migration 0076) + cache-first pipeline; live x2 on M3.1-Flash proves reruns cost zero STT."
---

# Cloudfone transcripts persist to DB; MiniMax-M3.1-Flash everywhere

## What happened

- Ask: store CloudFone call transcripts in the DB (transcribe once, analyze later), verify locally with MiniMax for a zero-disruption prod deploy, and run everything on `MiniMax-M3.1-Flash`.
- Added `cloudfone_call_transcripts` (alembic `0076`, additive) + `CloudfoneCallTranscript` model + `DbTranscriptStore` (`backend/app/services/cloudfone_transcripts.py`) behind a `TranscriptStore` seam. `_attach_transcripts` is cache-first: hit → no WAV download, no STT; miss → download + STT + persist. Load/save both fail-soft per call — a cache outage costs only the cache, the letter always ships.
- Model rollout: every MiniMax code constant + test stub + docs row now says `MiniMax-M3.1-Flash` (config.py `minimax_agent_model`/`minimax_extractor_model`).
- Verification: 63 focused tests (5 new cache tests incl. rerun-idempotence), 4079 unit green, 2 real-PostgreSQL integration tests (migration-to-head + model roundtrip + unique `call_id` + session-usable-after-failed-write), ruff/pyright clean, inventory oracle digest unchanged (`b323ba2b…`, zero new egress sites).
- Live x2 (real vendor 2026-10-01 + real M3.1-Flash STT + LLM): run 1 = 4 downloads / 4 STT / 4 rows stored; run 2 = **0 downloads / 0 STT**, identical letter. One transient provider `httpx.ReadTimeout` in run 1's daily-insights call fail-softed exactly as designed.

## Decision

- Store keyed by vendor `call_id` (UNIQUE) with a `day` index so later analysis can query by date; per-save `commit()` so every row is durable the moment STT pays for it (reruns are then free).
- `save()` rolls back and re-raises on failure: one bad write never poisons the session or blocks the send.

## Next steps

- Data-owner decision: retention/TTL for these PII call-content rows (currently append-only).
- Consider caching the daily-insights LLM note per day too (it is recomputed on rerun; one transient timeout observed live).

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
