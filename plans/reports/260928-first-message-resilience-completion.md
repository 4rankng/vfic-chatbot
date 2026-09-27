# Completion — first-message silence (webhook 500 after inbound commit)

## Task record

- Task: "bot never answers the first message sent by user, only from second onward" — investigate
  prod, fix, commit, push, deploy.
- Root cause (prod-evidenced, conversation `0be0fb79…`, 2026-09-27 17:34 UTC):
  1. First delivery: webhook committed the inbound `messages` row, then the realtime event bus
     serialized the freshly-created conversation → pydantic lazy-loaded `channel_identity` outside
     the async greenlet (`MissingGreenlet`) → HTTP 500 after commit → no lock, no enqueue, no answer.
  2. Zalo redeliveries (+30s, +5m31s) passed the expired 8s dedup window and hit
     `uq_messages_conv_provider_message` → 500 again, forever. Only the reconcile sweep (2-4 min)
     could rescue; ingress could never recover.
  3. The post-commit event fan-out was failure-unsafe on the hot path.
- Files changed: `backend/app/services/conversation/bot_path.py` (three guards),
  `backend/tests/integration/test_first_message_resilience.py` (new),
  `docs/architecture/system-architecture.md` (sequence diagram + corrections table).
- Instructions retrieved: `AGENTS.md`, `docs/ops/deployment-guide.md` (§3 deploy flow, §7 health),
  `docs/architecture/system-architecture.md` (§2 ingress), `.claude/skills/ak-cook/SKILL.md`.
- Approval required: none (no protected paths; behavior fix on the hot ingress path is the
  user-requested change; no schema change — the partial unique index from 0047 is reused, not altered).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `tests/integration/test_first_message_resilience.py`: created conversations carry loaded `contact`/`channel_identity`; duplicate redelivery returns the existing row (single row, no version bump); event failure keeps the message durable — 3 passed |
| Diff is limited to the approved scope | PASS | One state-module file + tests + doc |
| Protected operations were avoided or approved | PASS | No alembic/config/webhook-file/prompt changes |
| Focused tests/checks pass | PASS | 3 passed (above); `ruff check` → clean |
| Broader regression tests pass when shared behavior changed | PASS | affected suites 151 passed; full non-integration suite run recorded in-session; integration lane run for touched modules |
| Lint passes for affected code | PASS | ruff clean |
| Type checking passes for affected code | N/A | repo defines no type checker |
| Build/import validation passes | PASS | full suite imports |
| Security and privacy impact reviewed | PASS | `ON CONFLICT` inference uses the existing 0047 index; no new PII in logs (conversation id only, per existing convention); redelivery path is idempotent so a retry cannot double-send (per-chat mutex guards the in-flight edge) |
| Performance and async-I/O impact reviewed | PASS | one `INSERT .. ON CONFLICT DO NOTHING RETURNING id` replaces the ORM add — one round-trip, no extra reads on the happy path; eager relationship refresh only on first-contact create |
| Accessibility and Vietnamese UX reviewed | PASS | no UI change; first message now answered within seconds via redelivery self-heal instead of 2-4 min reconcile |
| Error handling and compatibility reviewed | PASS | no-id callers keep the legacy plain-insert path; `MissingGreenlet` class of failure is closed at the source (loaded relationships), not just swallowed |
| Documentation impact handled | PASS | `system-architecture.md` §2 sequence + corrections table updated; `node scripts/check-doc-links.mjs` unchanged paths (routing docs untouched) |
| No new unlinked `TODO`/`FIXME`/`HACK` | PASS | none |
| Final `git diff --check` | PASS | recorded before commit |
| Final `git status --short` reviewed | PASS | recorded before commit |

## Result

- Overall status: PASS
- Remaining risks: none known. The two `progressive streamed text differs` prod ERRORs
  (17:31/17:37) are a pre-existing separate signal (mid-stream provider replacement) — not touched
  here; the surface-inventory digest guard was already updated in the previous commit for the
  verification-cap Redis sites.
