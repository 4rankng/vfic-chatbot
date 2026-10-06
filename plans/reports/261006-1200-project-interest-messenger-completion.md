# Agent Completion Report — Project interest: Messenger ad/ref → dự án

## Task record

- Task: make it possible to say **which dự án a candidate is interested in**,
  starting with the ad/post clue on **Messenger** (Zalo deliberately deferred:
  "hiện tại làm Messenger trước thôi, Zalo để sau").
- Scope: campaign `ref` → project resolution at inbound, a two-signal interest
  record (`post_link` + `chat_focus`), the read API, and the recruiter-facing
  row. **Not** in scope: the `ad_id` → project mapping table (ads with no
  `ref`), the Zalo link→project resolve call, Zalo Ads form polling, inbox-list
  columns/filters.
- Files changed (mine, 13): `services/lead/interest.py` (resolver + two-signal
  recorder + reader), `services/conversation/bot_outcome.py`,
  `services/candidate_extraction.py`,
  `conversation_messaging/infrastructure/ingress.py` (Messenger inbound
  resolve), `api/leads.py` + `schemas/lead.py` (read endpoint),
  `tests/integration/test_project_interest.py` (new), `tests/test_lead_viewer_scope.py`,
  `tests/test_runtime_surface_inventory.py` (route snapshot),
  `frontend/.../types.ts`, `ConversationContextPanel.tsx` + its test,
  `docs/architecture/system-architecture.md`, `docs/product/codebase-summary.md`.
  The worktree also carries the still-uncommitted **attribution** feature
  (Alembic `0069`, 21 files) and an **unrelated in-flight session** (`app/graph/*`,
  `email_digest/*`, parts of the inventory test) — none of which I staged.
- Instructions retrieved: `AGENTS.md`; `docs/development/code-standards.md`;
  `docs/development/testing.md`; `docs/architecture/system-architecture.md`;
  `standards/agent-completion-checklist.md`.
- Approval required: commit / push / deploy for this work (none requested yet).
- Approval evidence: N/A — verified locally, awaiting the user's word.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Messenger inbound with a campaign `ref` resolves the project (`interest.py::resolve_project_by_code`, case-insensitive `projects.slug` or any `aliases` entry) and stores it as `attribution.project_id` (`conversation_messaging/infrastructure/ingress.py::persist`) **before the candidate types**; both signals then land as one idempotent `lead_events` row per (lead, project) with `source` (`post_link` / `chat_focus`); readable via `GET /api/v1/leads/{id}/project-interests` and the "Dự án quan tâm" row of `ConversationContextPanel`. Zalo capture keeps working; its resolve call is intentionally not wired (deferred by the user). |
| Diff is limited to the approved scope | PASS | `git diff --stat` over my 11 tracked files (+2 new) only; foreign in-flight edits listed above left untouched. |
| Protected operations were avoided or approved | PASS | No commit, push, branch, PR, or deploy performed. No new migration — interest rides the existing `lead_events.payload` JSONB (the `0069` column belongs to the earlier, also uncommitted, attribution task). |
| Focused tests/checks pass | PASS | `pytest tests/integration/test_project_interest.py -m integration` → **6 passed** (idempotence, outcome seam signal-driven, extraction backstop, reader order/renames/deleted-project, `resolve_project_by_code` match rules, and the full Messenger chain: referral → `attribution.project_id` → `post_link` event → dedup). Focused set (bot_outcome contract, extraction, attribution, viewer scope, inventory, ingress) → **264 passed**. Frontend: `vitest --project app` on the panel → **14 passed** (interests shown, omitted when empty, failed read never surfaces as an error). |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -m "not integration"` → **3685 passed, 28 skipped, 0 failed** (21m12s) on the combined tree (including the other session's WIP). Frontend `npm run typecheck` → exit 0. |
| Lint passes for affected code | PASS | `ruff check .` → "All checks passed!"; `eslint` on the three changed frontend files → exit 0. |
| Type checking passes for affected code | PASS | `tsc --noEmit -p tsconfig.app.json` → exit 0; `uvx pyright app/graph` → 0 errors (release-gate scope; this round touches `app/services`, `app/conversation_messaging`, `app/api`, `app/schemas`, frontend). |
| Build/import validation passes for affected code | PASS | Real-PostgreSQL integration tests import and execute every changed module (disposable DB runs Alembic head incl. 0069); `python -c "import app.conversation_messaging.infrastructure.ingress, app.services.candidate_extraction, app.services.conversation.bot_outcome"` → ok. |
| Security and privacy impact reviewed | PASS | The resolved code is a project slug/alias (no PII, no secrets); the resolver reads only the project catalog and **never raises** on the inbound path (a failure degrades to "no project", never a dropped message). The new endpoint reuses the viewer-scoped `_load`, so a recruiter still cannot read another recruiter's lead (4 paths re-asserted below). No new raw-payload storage. |
| Performance and async-I/O impact reviewed | PASS | One extra `SELECT` **only when a campaign code is present** (campaign inbound, not every message), over the small `projects` table; the recorder early-returns before any query when the conversation carries no signal; the interest write is one INSERT in its own post-outcome commit. No new tasks, loops, or per-turn cost on organic traffic. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | The row reuses the existing `CandidateInfoRow` (label + value + state icon) inside the priority list — same semantics as its siblings; Vietnamese label "Dự án quan tâm"; shown only when data exists (no empty-state noise). Real-browser rendering asserted by the vitest-browser tests (visibility + text), including the layout proof captured during the red run. |
| Error handling and compatibility reviewed | PASS | Recorder: swallow + rollback (outcome row and extraction job are load-bearing). Resolver: returns `None` on any failure. Unmatched code keeps `post_code` and simply resolves to no project. Recorder signature change migrated **both** callers (grep: 2 call sites + definition, no stale `source=` kwargs). `attribution`/`project_interest` remain optional → old rows/clients unaffected. |
| Documentation impact handled | PASS | `system-architecture.md` §2.5 rewritten (signal table, corrected seam rationale — the conversation trigger already creates the lead — code→project convention, Messenger-first note); `codebase-summary.md` module row updated. `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets … resolve". |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff -- <my files> \| grep -cE '^\+.*(TODO\|FIXME\|HACK)'` → 0. |
| Final `git diff --check` passes | PASS | `git diff --check -- <my files>` → exit 0. |
| Final `git status --short` reviewed | PASS | 43 paths: my attribution + interest files plus the unrelated session's `app/graph/*`, `email_digest/*` and inventory edits — reviewed, deliberately unstaged. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - **Nothing is committed or deployed yet** for either task in this thread
    (production still runs `aa1eeb7b`, i.e. without `0069`/attribution/interest).
    `make release-check` must pass before `make deploy` — the deployment-guide
    HEAD line already names `0069_conversation_attribution`.
  - **Messenger Page must be reconnected once** (disconnect → connect) so Meta
    subscribes `messaging_referrals`; without it ad referrals never arrive.
  - **Ads with no `ref`** resolve to no project — that needs the planned
    `ad_id/post_id → project` mapping table (Bước B), not built.
  - **Zalo resolve is one call away** (`services/webhook.py`) once wanted; a
    Zalo code must contain a digit, so it should be registered as a project
    *alias* (e.g. `lgd26`).
  - Marketing must put the **project slug in `ref`**
    (`https://m.me/<page>?ref=<slug>`, also as the CTM ad destination) — the
    mapping is a convention, not a table.
  - The worktree mixes my two tasks with another session's WIP: commit by
    explicit file list, never `git add -A`.
