# Kanban sweep 260927-1539 — docs cards DOC-14 … DOC-18 — completion report

## Task record

- Task: Implement documentation kanban cards DOC-14, DOC-15, DOC-16, DOC-17, DOC-18 (lane-docs).
- Scope: Docs-only corrections of stale counts, phantom names, dead references, and wrong
  enumerations in TECH.md, docs/, and standards/, exactly as the five cards prescribe.
  No source-code changes, no commit, no `git add`.
- Files changed (11):
  - `TECH.md`
  - `docs/testing.md`
  - `docs/codebase-summary.md`
  - `docs/code-standards.md`
  - `docs/qa-runbook.md`
  - `standards/coding-style.md`
  - `standards/performance.md`
  - `standards/definition-of-done.md`
  - `standards/review-checklist.md`
  - `standards/ui-guidelines.md`
  - `standards/prompt-library/README.md`
- Instructions retrieved: AGENTS.md, the five kanban cards in `kanban/TODO/20260926_DOC-1[4-8]-*.md`,
  and the targeted sections of each doc edited.
- Approval required: none triggered (no migrations, no webhooks/auth/security, no dependency
  changes, no deployment, no source code).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All five cards' prescribed corrections applied and re-verified by a stale-token sweep (see ledger below); final sweep `grep -rn "<stale tokens>" <11 docs>` returns no hits outside two legitimate statements (TECH.md:49 "react-virtuoso is no longer a dependency", TECH.md:105 "no GraphDeps.safety seam"). |
| Diff is limited to the approved scope | PASS | `git diff --stat -- TECH.md docs standards` = 11 files, +37/−42; every changed file is TECH.md, docs/, or standards/. `git diff --check` clean. |
| Protected operations were avoided or approved | PASS | No source, migrations, workflows, Makefiles, dependency manifests, or protected paths touched; no commit/add/push. |
| Focused tests/checks pass | PASS | Docs-only change; check = verification sweep + targeted greps/reads cited in the ledger (ports.py, vitest.config.ts, alembic versions, docker-compose.yml, Makefile release-check, package.json, HLD.md). |
| Broader regression tests pass when shared behavior changed | N/A | No shared behavior changed — no source files touched. |
| Lint passes for affected code | N/A | Markdown only; no lint gate applies. |
| Type checking passes for affected code | N/A | Markdown only. |
| Build/import validation passes for affected code | N/A | Markdown only. |
| Security and privacy impact reviewed | PASS | No secrets, PII, or message content introduced; corrections remove phantom symbol names only. |
| Performance and async-I/O impact reviewed | N/A | Docs only. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI changes. |
| Error handling and compatibility reviewed | N/A | Docs only. |
| Documentation impact handled | PASS | This task IS the docs correction; all five cards' target docs now match the current tree (verification ledger below). |
| No new unlinked TODO/FIXME/HACK | PASS | No TODO/FIXME/HACK added. |
| Final `git diff --check` passes | PASS | `git diff --check` → no output (clean). |
| Final `git status --short` reviewed | PASS | Working tree contains only: my 11 doc files, the parallel session's pre-existing dirty files (`.claude/CLAUDE.md`, `backend/app/services/knowledge/category_projections.py`, `backend/app/services/profile_enrichment.py`), and pre-existing deletions from before this session. No git add/commit run. |

## Verification ledger — every claim re-checked against current HEAD before editing

Key environment facts discovered during verification (HEAD moved since the audit at `31d30377`):

- GitHub Actions was dropped in `e7010b22` ("chore(ci): drop GitHub Actions and gate releases
  locally", 2026-09-26). `.github/workflows/quality-gates.yml` no longer exists; the gate set
  now lives in the root `Makefile` `release-check` target.
- Migration head has advanced past the card's `0055` prescription to
  **`0056_project_external_api`** (revises `0055_memories_match_halfvec`; verified by reading
  `revision`/`down_revision` in both files; `docs/deployment-guide.md:245` already names 0056).

### DOC-14 — TECH.md

| Card claim | Current-truth check | Action |
|---|---|---|
| :21 head `0054_channel_account_projects` stale | `ls backend/alembic/versions/` shows 0055 + 0056; 0056 `down_revision="0055_memories_match_halfvec"` | **Fixed → 0001–0056, head `0056_project_external_api`** (not the card's 0055; head moved again) |
| :52 two Vitest projects | `vitest.config.ts:6` "One test project"; `package.json` scripts have `test:unit:app` only, no `test:unit:claude` | **Fixed → "one `app` project, Playwright browser mode"** |
| :87-88 phantom `RetrievalPort` | `ports.py` defines ConversationPort:145, TurnDecisionsPort:62, LeadContextPort:200, RuntimePolicyPort:213, GraphRetrievalPort:223, FaqBypassPort:265; no RetrievalPort | **Fixed → six-port set: ConversationPort, GraphRetrievalPort, LeadContextPort, FaqBypassPort, TurnDecisionsPort, RuntimePolicyPort** (card-prescribed set) |
| :105-107 phantom `GraphDeps.safety` / `MiniMaxSafety` | `grep MiniMaxSafety backend --include=*.py` → 0 hits; `graph/types.py:117-155` GraphDeps has no `safety` field; `graph/think_strip.py:58` `strip_think_reasoning` exists | **Fixed → "no LLM safety judge … no `GraphDeps.safety` seam — the only user-visible reply transform is `graph/think_strip.py:strip_think_reasoning`"** |
| CI docs-drift guard only greps deployment-guide | `.github/workflows/` no longer exists (e7010b22); alembic-HEAD docs-drift check now in root `Makefile:39-42` (still greps only deployment-guide.md) | **Not implemented** — CI/Makefile edits are outside this lane's allowed files (docs-only cards). Noted as follow-up. |

### DOC-15 — docs/testing.md

| Card claim | Current-truth check | Action |
|---|---|---|
| :100-101,:117 claude vitest project + script | vitest.config.ts = one project; package.json has no such script | **Fixed** — setup bullet rewritten to one project; `test:unit:claude` command deleted |
| :100,:184 "80% only on changed/high-risk surface" denies the ratchet | `vitest.config.ts:19-45`: whole `src/components/atomic-crm/**` ratchet floors 67/55/57/68 + three 80% per-file gates (kernel/index.tsx, SecretField.tsx, PerformanceTrendChart.tsx) | **Fixed** — both sites rewritten to whole-atomic-crm ratchet + three 80% gates; backend noted report-only (pytest-cov dev dep, no threshold in `backend/pyproject.toml`) |
| :170-174 CI table predates functional-e2e split | **Already-resolved**: `e7010b22` already rewrote testing.md:166-180 to the local `make release-check` gates; verified table matches `Makefile:35-56` lane-for-lane (ruff+pytest unit / lint+typecheck+registry+unit+coverage+build / golden benchmark+release_gate_check with RELEASE_GATE_LATENCY_SLO_ENABLED=false) | **Not edited — recorded as already-resolved** (current text is accurate) |
| :52,:69 test_fast_lane.py + `-k "test_fast_lane"` | `ls backend/tests` has no fast_lane file; `test_graph_decisions.py` + `test_model_tiering.py` exist | **Fixed** — Fast-lane row → Decisions/FAQ row (test_graph_decisions.py, test_model_tiering.py, test_faq_bypass.py); `-k` example line deleted |
| :44 phantom RetrievalPort | same ports.py evidence as DOC-14 | **Fixed → identical six-port list** (per DOC-17's "identical everywhere" requirement) |

### DOC-16 — react-virtuoso sweep + 65-test-file count

| Card claim | Current-truth check | Action |
|---|---|---|
| performance.md:136 react-virtuoso mandate | package.json:73 `virtua ^0.49.2`; zero react-virtuoso in any manifest | Fixed → virtua (VList) |
| performance.md:159 checklist item (same file) | — | Fixed → virtua (VList) |
| performance.md bundle chunk list `virtuoso-vendor` | `vite.config.ts:123-124` chunk is `virtua-vendor` | Fixed → virtua-vendor |
| definition-of-done.md:72 react-virtuoso | — | Fixed → virtua (VList) |
| definition-of-done.md:40 "all 65 test files pass" | `ls backend/tests/test_*.py \| wc -l` = 195 | **Fixed → "all unit + integration tests pass"** (hardcoded count dropped) |
| review-checklist.md:27 react-virtuoso | — | Fixed → virtua (VList) |
| ui-guidelines.md:75 react-virtuoso | — | Fixed → virtua (VList) |
| prompt-library/README.md:180 react-virtuoso | — | Fixed → virtua |
| qa-runbook.md:406-407 react-virtuoso + HLD citation | HLD.md contains no virtu* text at all → the "(per docs/HLD.md)" citation dangles | **Fixed → "virtualized with `virtua` (`VList` — see `ChatThread.tsx`)"**, dangling HLD citation dropped |
| qa-runbook.md:399 chunk list `virtuoso-vendor` | same vite.config.ts evidence | Fixed → virtua-vendor |
| code-standards.md:189 stale parenthetical | — | **Fixed** — parenthetical dropped per card |
| — | code-standards.md:238 second `virtuoso-vendor` chunk list; :270-273 two-project Vitest + `test:unit:claude` (same dead-infrastructure class as DOC-15, file authorized by DOC-16) | **Fixed** — chunk name + one-project rewrite |

### DOC-17 — coding-style.md + testing.md port list

| Card claim | Current-truth check | Action |
|---|---|---|
| coding-style.md:22 RetrievalPort | ports.py evidence above | **Fixed → identical six-port list** |
| docs/testing.md:44 same | done under DOC-15 | Fixed |
| HLD.md / system-architecture.md carry no stale name | `grep virtu\|RetrievalPort docs/HLD.md` → no hits | Confirmed, left untouched |

### DOC-18 — docs/codebase-summary.md (+ TECH.md:59)

| Card claim | Current-truth check | Action |
|---|---|---|
| :40 "through 0054" | 0056 exists (evidence above) | **Fixed → "through 0056"** |
| :178 phantom `graph/tools.py` key-files row | `ls backend/app/graph/` — no tools.py; `schemas.py:32` TOOL_SCHEMAS, `:412` _dispatch_tool; `tools/` package holds jobs/knowledge/memory/income/catalog/tingting_api/tingting_identity/_shared | **Fixed** — row → `graph/schemas.py`; added `graph/tools/` row naming the per-domain modules |
| :46,:210 13-service count, no metrics-watch | `backend/docker-compose.yml`: 14 always-on services (postgres, redis, web-blue, web-green, worker-chatbot, worker-persistence, worker-ingest, scheduler, worker-followup, worker-maintenance, metrics-watch, frontend, adminer, caddy); only `oa-profile-backfill` has `profiles: ["maintenance"]` (compose :439); metrics-watch is always-on `restart: unless-stopped` | **Fixed** — both rows → 14 services + metrics-watch added to the enumeration; TECH.md:59 → 14 |
| :4 Last updated 2026-09-24 | — | **Fixed → 2026-09-27** |
| card note: metrics-watch may be uncommitted OPS-25 work | `git diff HEAD -- backend/docker-compose.yml` → clean (metrics-watch is committed) | Safe to correct the docs |
| — | tree row :22-24 and module map :127 still listed phantom `safety`/`safety.py` in graph/ (file removed; `ls backend/app/graph/` has no safety.py) — same phantom-name class in an authorized file, contradicting the doc's own think_strip row | **Fixed** — tree row → "tools/, schemas, think_strip"; module-map row → "`think_strip.py` provider-artefact stripping" |

## Not implemented / out of scope (reported, not edited)

1. **DOC-14's CI-hardening suggestion** (extend the docs-drift guard to TECH.md, or drop the
   revision id from TECH.md). `.github/workflows/` no longer exists; the alembic-HEAD drift
   check now lives in the root `Makefile:39-42` and still greps only deployment-guide.md.
   Makefile/workflow edits are outside this docs lane's allowed files, so TECH.md still carries
   an unguarded head marker (now correct at 0056). Follow-up candidate.
2. **docs/chatbot-latency-improvement-plan.md:150,293** still cite `backend/tests/test_fast_lane.py`.
   That file is a historical plan record (not named by any card, and plan docs are stateful
   records, not evergreen docs), so it was left untouched.
3. **DOC-15's reference to six CI jobs** in quality-gates.yml is moot — the workflow file was
   deleted in `e7010b22`; the card's CI-table item is superseded by the local-gates rewrite that
   commit already made to testing.md:166-180 (verified accurate against Makefile:35-56).

## Result

- Overall status: **DONE**
- Remaining risks or follow-ups: (1) TECH.md's Alembic-head marker remains unguarded by the
  release-check drift check (DOC-14's CI-hardening half is a Makefile change, outside this
  lane's file allowlist); (2) `docs/chatbot-latency-improvement-plan.md` retains historical
  `test_fast_lane.py` references; (3) test-file count is 195 today — the DoD no longer
  hardcodes a count, so no further rot there.
