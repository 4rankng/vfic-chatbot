# Kanban sweep 260927 — the 47-card tech-debt board — completion report

> **Status: the sweep is complete and the release gate is green at `e3bd9177`.**
> The gate was *not* green when this report was first written — the sweep itself had broken it
> (§4 D0). The defect is kept in full below because "this sweep broke the release gate, the review
> caught it, the lead fixed it" is the single most useful thing in this document.

## Task record

- Task: close out the 2026-09-27 kanban sweep of the read-only tech-debt audit board.
- Scope of this document: the durable completion record for the sweep. No source change,
  no card edit, no `git add`/`commit`/`checkout`/`stash`/`restore` was run to produce it.
- Board at HEAD: `kanban/TODO` = **2** cards, `kanban/QA_TESTED` = 159, `kanban/DEV_COMPLETED` = 12
  (observed: `for d in TODO QA_TESTED DEV_COMPLETED; do ls kanban/$d | wc -l; done`).
  Both TODO cards are **deliberately-open defects, not unfinished work** — see §5.1 (OPS-28) and
  §5.5 (DOC-19).
- HEAD when the verification below was last re-run: **`e3bd9177`**. The report was first written at
  `79a2b6a8` and revised at `e3bd9177`; every count is labelled with the HEAD it was taken at.

## Premises in the assignment that did not hold at HEAD

Recorded because a reader who was told otherwise will look for these files and not find them.

| Stated premise | Observed at HEAD | Evidence |
|---|---|---|
| `AGENTS.md` defines the completion contract | **Deleted.** No root `AGENTS.md` at HEAD. Now a tracked card: **DOC-19**, `kanban/TODO/20260927_DOC-19-...md`, opened `e3bd9177` (§5.5). | `git show --stat 65069078` → `AGENTS.md \| 83 --`; `find . -name AGENTS.md` returns only `frontend/AGENTS.md` and `.claude/skills/ak-react-best-practices/AGENTS.md` |
| `standards/agent-completion-checklist.md` is the gate list | **Deleted**, along with the whole `standards/` directory. Covered by DOC-19. | `git show --stat 65069078` → `standards/agent-completion-checklist.md \| 41 -`, plus `coding-style.md`, `definition-of-done.md`, `performance.md`, `prompt-library/README.md`, `review-checklist.md`, `security.md`, `ui-guidelines.md` |
| The commit series `08003ea4..758243d4` is 35 commits | `git rev-list --count 08003ea4..758243d4` = **33**. | run at HEAD `79a2b6a8`, unchanged at `e3bd9177` |
| …35 commits is the sweep | At `79a2b6a8`: `b33c3c97..HEAD` = 36, `b33c3c97~1..HEAD` = 37. At `e3bd9177`: `b33c3c97..HEAD` = **38**, `b33c3c97~1..HEAD` = **39** (that form includes the base `b33c3c97` Repowise refresh). The two later commits are `ca7be4d8` (the gate fix, §4 D0) and `e3bd9177` (the DOC-19 card). | `git rev-list --count` at `e3bd9177` |
| `ruff format --check` fails on 306 files | **320** files: `320 files would be reformatted, 461 files already formatted`. | `cd backend && .venv/bin/ruff format --check .` |
| 11 pre-existing prettier deviations | **20** files. 9 of the 20 were touched by this sweep. | `cd frontend && npx prettier --config ./.prettierrc.json --list-different "**/*.{mjs,js,json,ts,tsx,css,md,html}"` → 20 lines; per-file sweep-touched check via `git log b33c3c97~1..HEAD -- frontend/<path>` |

Because the checklist file is gone, the gate list below is reconstructed from the most recent
completion report in the same series, `plans/reports/kanban-sweep-260927-1539-docs-completion.md:28-45`
(16 gates, house format). I did not invent or drop a gate. **That forced reconstruction is itself a
tracked finding** — DOC-19 names this report as the concrete evidence that the gate list now lives
only in whichever report happened to be written most recently.

HEAD moved under me four times while this report was written: `dc119688` and `79a2b6a8` (kanban
bookkeeping), then `ca7be4d8` (the release-gate fix) and `e3bd9177` (the DOC-19 card). Counts are
labelled with the HEAD they were taken at; the two kanban-move commits are bookkeeping, not
implementation.

---

## 1. Scope and outcome

**45 of 45 original cards implemented. Two new cards opened and deliberately left open: OPS-28
(§5.1) and DOC-19 (§5.5).**

The board held 47 tech-debt cards: 45 moved `TODO` → `QA_TESTED` in `dc119688`
(`git show --name-status --find-renames dc119688 | grep -c '^R'` = 45), plus SEC-9 and OPS-25
which closed in `08003ea4` at the head of the series. Every one of the 45 now carries
`status: done` and the state line `DONE — implemented and committed 2026-09-27`.

`kanban/TODO` holds two files, and **neither is unfinished sweep work**:

- `20260927_OPS-28-the-migration-chain-cannot-reach-base-0006-downgrade-drops-publis.md` — the
  migration chain cannot reach base. Found by the backend gate, pre-existing, migration edits are
  approval-gated (§5.1).
- `20260927_DOC-19-restore-or-redirect-the-repository-constitution-deleted-in-65069078.md` — the
  repository constitution (`AGENTS.md` + `standards/`) was deleted and nothing routes around it.
  Found while writing this report (§5.5).

### Commit series, grouped by area prefix

`git log --oneline b33c3c97~1..HEAD` = **39** lines at `e3bd9177` (37 at `79a2b6a8`, plus
`ca7be4d8` and `e3bd9177`). Grouped on the conventional-commit scope:

| Area prefix | n | Commits |
|---|---|---|
| `chore(kanban)` | 5 | `08003ea4` `89758aaf` `dc119688` `79a2b6a8` `e3bd9177` |
| `refactor(graph)` | 2 | `d9018544` `6a434f8e` |
| `refactor(conversation)` | 2 | `56b6d0f9` `45e747b0` |
| `fix(tests)` | 2 | `6dd3e9f3` `911bfdb5` |
| `fix(registry)` | 2 | `3a75d96e` `20b820e0` |
| `fix(ops)` | 2 | `9a8f74fc` `14ddcabb` |
| `chore(testing)` | 2 | `ff4d8b0c` `af359276` |
| `test` (unscoped) | 2 | `55dd322e` `758243d4` |
| `test(frontend)` / `test(platform)` / `test(leads)` / `test(conversation)` / `test(testing)` | 5 | `1e686704` `e6ea7810` `bd0fd052` `1b920ef0` `178a8a03` |
| `refactor(integrations)` / `refactor(frontend)` / `refactor(knowledge)` / `refactor(seed)` / `refactor(zalo)` | 5 | `7c746da5` `d7bed8c1` `21ac7cb9` `e9a3a459` `786ca8bd` |
| `fix(ratelimit)` / `fix(knowledge)` / `fix(graph)` | 3 | `d2cab403` `1fa81c0b` `14d61246` |
| `style(registry)` / `style(integrations)` | 2 | `0a33186c` `e4e03740` |
| `perf(retrieval)` / `feat(smoke)` | 2 | `0eaf8b5c` `98b9b5e8` |
| `chore(context)` / `chore` (unscoped) | 2 | `5f69e2a0` `b33c3c97` |
| `fix(docs)` | 1 | `ca7be4d8` — the §4 D0 release-gate fix, landed after this report's first draft |

Grouping note: the prefix is cosmetic — several commits carry two or three cards, and several
cards span two or three commits. The per-card mapping in §3 is the authoritative one.

---

## 2. Completion gates

Every gate from the reconstructed 16-gate list, filled. Results from the lead's own gate runs are
marked *(lead)*; everything else I ran myself, at the HEAD labelled.

Two gates were **BLOCKED** when this report was first drafted at `79a2b6a8` because the sweep had
left `make release-check` red (§4 D0). Both are re-evaluated below at `e3bd9177`; the D0 finding
itself is retained in full.

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All 45 cards implemented and committed, and the release gate now passes. **Was BLOCKED at `79a2b6a8`:** the sweep's own migration `0057` (`0eaf8b5c`, PERF-17) left `docs/ops/deployment-guide.md` naming `0056_project_external_api`, so the `Makefile:51-53` docs-drift grep failed. Found by this report (§4 D0), fixed by the lead in `ca7be4d8`. Replayed verbatim at `e3bd9177`: `DOCS DRIFT GATE: PASS`, `SINGLE HEAD: PASS`, `HEAD_REV=0057_drop_match_memories_vector_overload`. |
| Diff is limited to the approved scope | PASS | `git status --short` = ` M .claude/CLAUDE.md` (Repowise's own auto-update; not authored by any of this work, not staged) plus this untracked report. `git diff --check` → no output, exit 0. No git mutation was run at any point. |
| Protected operations were avoided or approved | PASS | No git mutation was run to produce this report. Migration edits were **not** made despite the chain being broken (OPS-28 stayed open for exactly that reason). `backend/app/core/ratelimit.py` — named protected in REL-11's own Notes — *was* edited, on the card's explicit instruction ("Use a small Lua script…"). |
| Focused tests/checks pass | PASS | `cd backend && .venv/bin/ruff check .` → `All checks passed!` (exit 0), re-confirmed at `e3bd9177`. `cd backend && .venv/bin/python -m alembic heads` → exactly one line, `0057_drop_match_memories_vector_overload (head)`. `cd frontend && npm run typecheck` → clean. `npm run lint` → clean. `npm run registry:check` → `Registry paths and local text dependencies are complete (268 files).` Backend unit lane *(lead, final)*: **2,693 passed, 28 skipped, 142 deselected, 0 failed** in 249 s; coverage **76.55 %** over 26,987 statements, 6,328 missed, ratchet floor 75 reached. Frontend *(lead, final)*: **662 tests across 116 files** (baseline 615/114). The earlier figures in this report (2,642 / 24 / 76.2 % / 26,780 / 6,387) were superseded by these. |
| Broader regression tests pass when shared behavior changed | PASS on the lanes run; **incomplete on the integration lane** | Shared behavior did change (rate limiter, graph turn lane, conversation split). The release gate's own lanes are green *(lead)*: `Makefile:54` unit and `Makefile:55` frontend unit + coverage + build. **The integration lane is not in the release gate** — `Makefile:54` passes `-m "not integration"` — so the lead ran the sweep-relevant subset deliberately *(lead)*: `test_memories_halfvec_index_migration.py`, `test_chatops_followup_calendar.py`, `test_smoke_turn_invariant.py`, `test_turn_pipeline_check.py` → **17 passed in 92.56 s**. **The full integration lane did not complete**: it exceeded the 300 s harness cap twice, and `test_migration_roundtrip_walk.py` alone takes ~342 s, so it was not run to completion. That lane is an **unverified area**, not a green one. See §7.2. |
| Lint passes for affected code | PASS | `ruff check` clean. `eslint "**/*.{mjs,ts,tsx}"` clean. `ruff format --check` **fails on 320 files** — pre-existing, not in the gate (`Makefile:54` runs `ruff check` only), deliberately not fixed (§5.2). |
| Type checking passes for affected code | PASS | `npm run typecheck` → `tsc --noEmit --project tsconfig.app.json`, no output. The sweep also *removed* a file that was breaking this gate: `__tingting-look.test.tsx` (`20b820e0`). |
| Build/import validation passes for affected code | **BLOCKED** — residual, and now for an unrelated reason | The §4 D0 blocker is **resolved**. What remains is that `make release-check` still refuses to start: `Makefile:47` opens with `test -z "$(git status --porcelain)"` and the working tree is dirty (`.claude/CLAUDE.md`, Repowise's own auto-update, §7.5). I did not run `npm run build` or the golden-benchmark leg (`Makefile:56+`) myself; the lead's run covers both. Nothing in this report's scope is unbuilt, but the target has not been executed end-to-end. |
| Security and privacy impact reviewed | PASS | The one security-relevant change is SEC-11, reviewed in §6 (argv credential exposure removed; residual Env exposure is pre-existing and inherent to `env_file`). SEC-10 bounds the multipart read to `MAX_UPLOAD_BYTES + 1` — an improvement, not a regression. SEC-9 closed as an explicit, documented owner risk acceptance with four named re-decision triggers (`kanban/QA_TESTED/20260926_SEC-9-...md:18-36`). No secret value is written into this report. |
| Performance and async I/O impact reviewed | PASS | PERF-15 (ack path 3 refreshes → 1 column-scoped), PERF-16 (shared client cache), PERF-17 (halfvec index) are all reductions, and each is a named card. The one perf-relevant regression to check is the boundary-inventory sensitivity drop in §7.1, which is a *detection* regression, not a runtime one. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | FE-24 routes the remaining hardcoded Vietnamese through the message catalog (semi-auto takeover notices, the "Lưu & kiểm tra" button, integration button/footer strings) rather than leaving strings inline. TEST-23 pins `aria-invalid` plus focus management on `PersonaForm`. `resources.conversations.reply` was reached dynamically from ChatThread and was deliberately **kept** during the FE-23 prune (`7c746da5`). I found no user-visible copy change that drops or rewords a Vietnamese string. |
| Error handling and compatibility reviewed | PASS | ARCH-22's strict branch reproduces the old detector's decisions *and* its two `ValueError` messages verbatim, so a rejected upload still reads identically. ARCH-22's broken workbook now returns 422 instead of ingesting binary noise. ARCH-26 makes stale env keys `extra='ignore'` rather than raising at startup. REL-11's fail-open-on-Redis-down path was reviewed and left intact. |
| Documentation impact handled | PASS | Every card that changed a documented fact was updated in the same commit: `.coveragerc` header records the measurement and the raise procedure; `docker-compose.yml` carries the SEC-11 rationale at each of the six sites; `alembic/versions/0057` records why the overload was dropped in a new revision rather than by editing 0055; `tests/test_runtime_surface_inventory.py` documents the −5. The one documented fact the sweep got wrong — `docs/ops/deployment-guide.md:245` — is now corrected in `ca7be4d8`, which also records what `0057` does so the next reader learns why the vector overload is gone. A second documentation gap, the missing repo constitution, is now **DOC-19** (§5.5). |
| No new unlinked TODO/FIXME/HACK | PASS | I did not add one; this file is prose. No source file was edited by me. |
| Final `git diff --check` passes | PASS | `git diff --check` → no output, exit 0. |
| Final `git status --short` reviewed | PASS | Four entries, all accounted for: ` M .claude/CLAUDE.md` (Repowise's auto-update, not authored here), ` M …/capabilities/kernel/index.test.ts` and ` M …/capabilities/kernel/components.tsx` (the in-flight conversion, §7.4), plus this untracked report. Nothing staged, nothing committed, no git mutation run at any point. |

---

## 3. What each card actually got

"Asked" is the card's `## Suggested fix`. "Done" is what shipped. Divergences are called out.

### Architecture

| Card | Asked | Done | Commit |
|---|---|---|---|
| ARCH-20 | split the 2153-loc `graph/runner.py` | Outbound half moved to `graph/dispatch.py`; `_dispatch_claimed_message`'s two `send_message` calls and `_status_heartbeat`'s `send_chat_action` re-keyed to the new home, same count | `d9018544` |
| ARCH-21 | extract the 719-line `MinimaxAgent.agent` out of the 1481-loc module | `clients.py` split by transport/concern into `embedders.py` `providers.py` `dispatch.py` `answer_repair.py` `progressive.py` `lanes.py` `authority.py` `telemetry.py`; `clients.py` keeps re-exporting the public names so the monkeypatched `get_settings` binding is unchanged | `d9018544` |
| ARCH-22 | consolidate the three diverged upload-extraction paths | `file_extraction.py` is the single owner; `_detect_upload_format` and `extract_text` gained `allowed_formats`; the private `service.py` duplicates deleted. **Diverged twice — see below** | `21ac7cb9`, rewritten `1fa81c0b` |
| ARCH-23 | split the 833-loc `KnowledgeCategoryService` | 841 → 602 LOC as a pure delegating facade; cutover/rollback to `category_authority.py`, `_render_units` to `category_projections.py`, `validate_active_job_references` to `category_contracts`. Public signatures unchanged, so `api/knowledge.py` and `api/projects.py` were untouched | `21ac7cb9` |
| ARCH-24 | shrink the `ConversationService` union facade | 48 public methods → 21; 27 dead forwarders deleted, every caller now names `svc.repo` or `svc.state` | `56b6d0f9`, `45e747b0` |
| ARCH-25 | split the remaining 600-loc modules | `repository.py` 721 → 473 (`_MASKED_INBOUND_SQL` defined once in `reconcile_queries.py`); `recruiter_path.py` 664 → 393 (receipt half → `recruiter_receipts.py`); `chatbot_worker.py` 714 → 608 (ASGI bridge → `direct_turn.py`); two entrypoints stay re-exported because `app/main.py` imports the drain | `56b6d0f9`, `45e747b0` |
| ARCH-26 | delete the orphan `settings.agent_max_seconds` and the stale `min_llm_time_budget` block | Both gone, plus the zero-reader `faq_abstain_margin`. Stale `AGENT_MAX_SECONDS` / `FAQ_FAST_LANE_ENABLED` are now `extra='ignore'` rather than startup-raising, with a test so nobody flips it to `forbid` | `6a434f8e` |
| ARCH-27 | remove the disabled FAQ-bypass lane | Adapter, port, result type, `GraphDeps` field, factory wiring, two schema enum members, `_STAGE_KEYS` / `_MEASURED_STAGES` and the `faq_bypass_ms` projection all deleted. `services/retrieval/faq_bypass.py` **kept** (still has its own suite; nothing in `app/` calls it) with a docstring saying so. Two named consequences: `faq_bypass_ms` now counts as unmeasured dark time for pre-existing rows, and a persisted trace naming the lane no longer parses | `6a434f8e` |
| ARCH-28 | apply the strip-stale-refusal rules to the direct-context persona | Both lanes go through one `resolve_effective_persona` in `context.py`. **One deliberate behaviour change, flagged in the commit**: the direct-context persona now fails soft to `persona.md` on a read error | `14d61246` |
| ARCH-29 | split the 2102-loc `seed_dev.py` | 85-line entrypoint re-exporting the 25-name fixture surface, 17-module package, one process-wide RNG preserved as the determinism contract. Fixture/ID/row-count inventory derived from a real seeded database | `e9a3a459` |
| ARCH-32 | flatten `_split_long_plain_text` from 5 levels to 1 | Guard clauses + four named helpers, one loop per rung. Proved by differential fuzz against the original algorithm reimplemented verbatim: 100k randomized + 294 hand-built edge cases, zero mismatches, byte-identical reply at the 1600-char cap | `786ca8bd` |

### Frontend

| Card | Asked | Done | Commit |
|---|---|---|---|
| FE-22 | certify **or** flatten the `integrations/` layer | **Chose flatten.** Reason is structural, recorded in `7c746da5`: adding `integrations` to `_FRONTEND_LAYERED_FEATURE_ROOTS` fires the layer rule, which rejects the `application/` branch for importing `react`, `ra-core` and `@tanstack/react-query`. Certifying would mean evicting all three hooks from `application/`, moving `api.ts` to `infrastructure/`, stripping 8 gateway imports out of `domain/providerDescriptors.ts`, **undoing the deliberate FE-01 design where descriptors carry their own gateway call**, routing five presentation modules through a new composition module — and the resulting port would have exactly one implementation. That is a redesign, not a port. 17 modules moved to the feature root; `integrations/index.tsx` states in a module comment that the feature is NOT certified, names the four pre-existing outward edges, and records the bar for re-introducing layer dirs | `7c746da5` |
| FE-23 | prune the 45 unreferenced catalog keys | 456 → 398 lines. `crm.settings`, `crm.theme`, `crm.auth`, six `crm.navigation`, `crm.profile.record_not_found`, four `crm.common`, two `resources.conversations`, the `ra-auth` block. Every leaf re-grepped including the dynamic-lookup sites; `resources.conversations.reply` is reached dynamically from ChatThread and was **kept** | `7c746da5` |
| FE-24 | route semi-auto takeover + integration button strings through the catalog | Semi-auto takeover success/error notices, "Lưu & kiểm tra", encrypted-token footer hint, integration button and footer strings. `messageArgs._` overrides in `ProfilePage` deleted so catalog values win | `7c746da5` |
| FE-25 | sync the `registry.json` dependencies block with `package.json` | `generate-registry.mjs` now derives the block by TypeScript-AST parsing of every published module's imports plus the `@import` rules of published stylesheets, pinned to `package.json`'s range, and throws a named error on an undeclared import. Was 14 stale + 12 missing; now 17 packages, none missing, none dev-only. `check-registry-paths.mjs` gained a gate over the block (previously invisible to it). Generator is idempotent — two consecutive runs byte-identical | `3a75d96e` |
| FE-26 | remove the four orphaned devDependencies | `@inquirer/prompts`, `@types/papaparse`, `@types/qs`, `@types/ms` removed. All three `@types` packages type libraries that are not installed at all | `3a75d96e` |
| FE-27 | extract `PersonaStudioOverview` (310-loc, CCN 27) | 290-line single-method render → ~74-line composition over five sections with narrow prop types; `PersonaPromptSection` takes `bodyMd` and calls the domain summariser itself rather than leaking the domain return type | `d7bed8c1` |
| FE-28 | decompose `ChatThread` (882-loc, CCN 92) | 882 → 621. Grouping → `conversations/domain/conversation-thread-rows.ts` (pure), bubble variants → `presentation/ChatMessageRow.tsx`, text splitting → `domain/conversation-message-text.ts`. The direct `providers/rest/dataProvider` import is gone behind a `use-conversation-operations` port, **closing the edge FE-08 recorded as a QA gate**. The existing 20-test ChatThread suite was not modified and is the behaviour-parity proof | `d7bed8c1` |
| FE-29 | split `PerformancePage.tsx` (1002 lines, 15 inline components) | 1002 → 237 as a composition root; 13 components → `performance/presentation/` grouped by window, `Status` and `Metric` shared through a primitives module | `d7bed8c1` |

### Reliability

| Card | Asked | Done | Commit |
|---|---|---|---|
| REL-8 | initialise `candidate` before the `try` in `run_proactive_turn` | **Already fixed in the tree at HEAD** — verified, not re-touched. No behaviour change | `14d61246` |
| REL-9 | pin the ChatOps schedule-followup `due_at` to ICT morning | **Already fixed in production code at HEAD.** What was missing was coverage: a new PostgreSQL integration test asserts a ChatOps-created followup converts to 09:00 ICT on the next Vietnam day and that the dashboard's real `_vn_today_predicate` matches the row at the recruiter's morning on the due day and not the day before. Asserts the ICT wall-clock hour, not a UTC offset coincidence; counter query is bound `:as_of` so it is clock-independent | `bd0fd052` |
| REL-10 | route ChatOps `apply_action` lead writes through optimistic apply | **Already fixed in production code at HEAD.** Coverage added: advances a lead to version 2 from a second session, asserts the stale-version apply raises `ConflictError` with `next_action_at` still NULL and no `FollowUpTask` row surviving. The existing unit case was hardened to mute the realtime bus so a regression reads `DID NOT RAISE ConflictError` rather than a pydantic error. Both mutation-checked against the pre-fix code | `bd0fd052` |
| REL-11 | make the bucket TTL establishment atomic with the INCR | **Implemented, then found wrong in review and rewritten.** See §4 D1 — this is the most serious event in the sweep | `786ca8bd` → **`d2cab403`** |
| REL-12 | stop rebinding `sem` in `MinimaxAgent.agent` | The tool-dispatch semaphore shadowed the name used for the Redis LLM concurrency cap, so post-tool rounds silently stopped counting against the deployment-wide limit. Tool semaphore renamed and confined to `_bounded`; every round reacquires the Redis semaphore | `14d61246` |
| REL-13 | terminalize the progressive early bubble when the lane fails mid-stream | A lane failing after the early bubble was delivered overwrote the row with `reply=''` — the candidate saw content and then an empty message. The delivered bubble is recorded when claimed; every terminal path (silent terminal, `LLMThrottled`, abandoned turn) finalises the outbox row first and records the outcome with the bubble text and the real send result | `14d61246`, gate wired in `98b9b5e8` |
| REL-14 | de-duplicate the fallback re-emission in LLM-call streaming | On a mid-stream provider failover the fallback's re-emitted prefix reached the candidate a second time. The overlap is detected against already-emitted text and only the genuinely new suffix is forwarded. A mid-stream stall now alarms on `progressive_stream_mismatch` instead of warning silently | `14d61246` |
| REL-15 | replace the `messages[1]` content-exhaustion fallback | Exhausting the tool loop fell back to `messages[-1].content`, re-sending a prompt- or tool-shaped string to the candidate. Now returns the lane's neutral unavailable text and records a `degradation_reason` | `14d61246` |

### Security

| Card | Asked | Done | Commit |
|---|---|---|---|
| SEC-9 | reinstate the deterministic output guard, **or** record an owner risk acceptance | **Owner chose risk acceptance.** No source change. The card records the verdict, the residual defences (`strip_think_reasoning`, `ground_reply`'s job-id/entity cross-check), and four named re-decision triggers — chief among them a prompt-injection incident reaching candidates through KB content. States plainly that re-decision trigger 1 converts this from accepted risk to live defect | `08003ea4` |
| SEC-10 | bound the admin multipart reads before the 20 MiB check | All three routes read through `read_upload_within_limit`, passing `MAX_UPLOAD_BYTES + 1` to `read()` — an oversized upload is rejected after one bounded read. A recording double asserts `read_sizes == [limit+1]`, never a whole-body read, and that the 413 detail is identical across both upload routes | `21ac7cb9` |
| SEC-11 | stop passing redis credentials as process arguments in four compose services and the redis healthcheck | `--url ${REDIS_URL}` removed from `worker-ingest`, `scheduler`, `worker-followup`, `worker-maintenance`; `redis-cli -a` replaced by `REDISCLI_AUTH` in the healthcheck. **Diverged from the card's prescription on one service**: the card says "rq and rqscheduler default to the REDIS_URL environment variable", which is false — `rqscheduler` defaults from `RQ_REDIS_URL` and otherwise falls back to localhost, so following the card literally would have silently disconnected the scheduler from the broker. An explicit `RQ_REDIS_URL` was added for that service only. The card also omits `redis-server --requirepass`, which is the one real remaining argv exposure (§5.4). See also §6 | `14ddcabb` |

### Ops

| Card | Asked | Done | Commit |
|---|---|---|---|
| OPS-21 | `make backup` fails at HEAD — the compose call trips the `${IMAGE_TAG}` guard | Tag resolved from the running active-colour web container, copied from the recipe `backup-droplet.sh` already uses. A new `RESOLVE_IMAGE_TAG` variable fixes the same bug class at six sibling call sites in `backend/Makefile`. `rollback` deliberately left alone — it derives `PREV_TAG` | `9a8f74fc` |
| OPS-22 | `bg_deploy` post-flip verification and deploy-breaking service lists | `worker-maintenance` and `metrics-watch` were missing from both lists, so a service could be skipped with nothing noticing. A test now derives the `${IMAGE_TAG}` service set from `docker-compose.yml` and asserts both lists cover it | `9a8f74fc` |
| OPS-23 | `ops-alerts.sh` docker checks dead on arrival | `cd`s to the absolute deploy root, validates `ACTIVE_COLOR`, resolves `IMAGE_TAG` from the running container, parses `docker system df`'s JSON fields numerically | `9a8f74fc` |
| OPS-24 | frontend and caddy have no healthcheck | Both added. The caddy probe checks the status code rather than `wget --spider`, because busybox wget **follows the 308** out of the container to the public host — `--spider` would make the probe depend on public DNS and egress | `14ddcabb` |
| OPS-25 | land the uncommitted 2026-09-26 bot-silence remediation | **Committed by the repo owner, not by this sweep.** Re-verified every item: `turn_pipeline_check.py` and both test files tracked, `bg_deploy.sh:295` and `bg_rollback.sh:245` invoke the gate post-flip, compose `start_period` budgets present including the `180s` that covers the 83 s worker preload. The docs sections landed under `docs/ops/` after the docs restructure. The remaining image cut is an operator deploy step, not an agent action | `08003ea4` |
| OPS-26 | silence the per-message "webhook accepted while runtime inactive" | Demoted to DEBUG with a once-per-process summary, plus a runbook note that it must never alert | `14d61246` |
| OPS-27 | add `base-uri` and `form-action` to the caddy CSP | Added. `upgrade-insecure-requests` deliberately **not** added: HSTS already pins the browser and this template is the prod auto-TLS vhost only, so it would break plain-HTTP local use for no gain | `9a8f74fc` |
| OPS-28 | *(opened by this sweep — deliberately not fixed)* | See §5.1 | `89758aaf` |

### Governance

| Card | Asked | Done | Commit |
|---|---|---|---|
| DOC-19 | *(opened while writing this report — deliberately not fixed)* | See §5.5. Recorded the missing repo constitution, the recovery command, and the link check that would stop a routing target from vanishing silently again | `e3bd9177` |

### Performance

| Card | Asked | Done | Commit |
|---|---|---|---|
| PERF-15 | cut the webhook ack path to one column-scoped conversation refresh | Three refreshes → one after `record_inbound`, loading only the columns the guards read. The pre-lock refresh is deliberately kept — that is what makes the takeover race guard correct. Verified the eight guard columns and the refresh-before-`acquire_lock` order are unchanged | `14d61246` |
| PERF-16 | cache the persistence-worker extractor and embedder clients | They now come from the shared cache. `aclose_client_cache` already tears the bundle down at shutdown, so no new lifecycle handling was needed | `14d61246` |
| PERF-17 | migration 0055's `halfvec match_memories` overload is never called | The query is now `CAST(:emb AS halfvec(3072))`, mirroring the `knowledge_chunks` path. The unused `public.match_memories(vector, …)` overload is dropped in a **new 0057 revision** rather than by editing 0055, so an environment that already applied 0055 does not silently diverge; the downgrade restores it, so it is symmetric | `0eaf8b5c` |

### Testing

| Card | Asked | Done | Commit |
|---|---|---|---|
| TEST-16 | execute `bg_deploy`'s rolling turn-worker recreate in the sandbox | The sandbox docker stub is now stateful: one replica removed and topped up at a time with `--scale` bookkeeping, never a blunt `force-recreate`; a rolled replica that never reports healthy aborts before the caddy flip with `ACTIVE_COLOR` untouched; a failing `turn_pipeline_check` rolls back. The ~20 lines of script text pins are gone | `9a8f74fc` |
| TEST-17 | retire the TEST-10 raw-source assertion tail (~135 sites across 14 files) | **Converted across two passes, and the first pass did not finish the job.** See the honest accounting below | `55dd322e`, `e6ea7810`, `1e686704`, `758243d4` |
| TEST-18 | engage the backend coverage ratchet (`fail_under` is 0) | `fail_under = 75` in `backend/.coveragerc:34`. **The floor was a projection twice before it was a measurement**: `ff4d8b0c` set it to 65 by arithmetic from a 3-day-old 74.8 % figure, and `af359276` replaced that with a real run — `TOTAL 76.2%` over 26,780 statements, 6,387 missed, 2,642 passing — set at that number minus the ~1 pt absorption margin the frontend floors already use. **A later run measures 76.55 % over 26,987 statements, 6,328 missed** *(lead, final)*, so the 75 floor holds 1.55 pt of headroom and has not been raised again. Two tests drive `coverage.results.should_fail_under` against the repo's own config; a second pins the denominator to the `app` package via `coverage`'s `GlobMatcher`. Both mutation-verified | `ff4d8b0c`, `178a8a03`, `af359276` |
| TEST-19 | install the functional-e2e backend from `uv.lock` instead of unpinned | **Premise was stale.** The unpinned `pip install` lived in `.github/workflows/`, which no longer exists (`e7010b22`). The production image path was already fixed (`uv export --frozen` + `pip install --require-hashes`). The surviving unpinned path is the root `Makefile` bootstrap, which is now `uv sync --frozen` with the old pip resolve kept as an explicit, labelled UNPINNED fallback. `codebase-summary.md` was corrected — it documented an install method the Dockerfile stopped using | `9a8f74fc`, `ff4d8b0c` |
| TEST-20 | hoist the triplicated `_reset_local_secret_cache` autouse fixture | Hoisted into `tests/conftest.py` as the union of the three local copies, which are deleted. Stays autouse so future secret-touching tests are covered by default | `786ca8bd` |
| TEST-21 | exercise progressive send in `scripts/smoke_turn.py` | The pre-flip deploy gate now runs three probes: single-message, progressive-send, progressive-send-with-a-failing-lane. The failure probe is the one that earns its keep — it streams a bubble, lets the transport acknowledge it, then kills the lane, and asserts the delivered bubble KEEPS its text and SENT state. ~5 s for all three, stable over three runs, 30 s bounded wait so a build that never dispatches fails the deploy instead of hanging it. **Proved by simulation, not assertion**: reverting the delivered-bubble record makes the gate exit 1 with a specific message | `98b9b5e8` |
| TEST-23 | give `PersonaForm.tsx` a behavioural test file (609 lines, 58 dependenc…) | 6 tests: required-field gates in order, `aria-invalid` + focus management, a real `Select` interaction (the only case that never went through `initial`), the empty-KB state, the full save payload, re-enabling after a rejected save. The in-flight window is a held promise, not a timeout. **Diverged**: the card asked for dirty-state gating; `PersonaForm` gates on `submitting`, not a has-changed flag, so the test pins the gate that actually exists | `d7bed8c1` |

### TEST-17's two passes, honestly

The card names 14 files (9 frontend, 5 backend) and ~135 source-text assertion sites.

- **Pass 1** landed across `55dd322e` (4 backend files + a new `compose_model.py` helper), `e6ea7810`, and `1e686704` (3 frontend source-text files deleted: `settings.css.test.ts`, `knowledge-workspace-layout.test.ts`, `tailkit-system.css.test.ts`; 4 behavioural `.tsx` specs added; 56 tests; the two invariants the pass dropped — performance z-index 3/2 and pointer-events layering, and the too-broad `not.toContain('tt-card')` — were both closed, with `elementFromPoint` hit-testing and a computed-`borderRadius`/shadow/background/`[data-slot=card]`-descendant check).
- **The first pass did not finish.** `758243d4`'s own message opens "Finishes TEST-17" and names the outstanding set: 5 frontend specs plus the backend security-headers test. Those landed in `758243d4` (11 files, +2420/−421). Notably the security-headers test turned out to be **fully** convertible rather than the documented exception the card anticipated — `caddy adapt` performs the same Caddyfile→JSON adaptation as `caddy reload` on the droplet, so each test renders the template through the exact sed `flip_caddy.sh` uses and walks the resulting route tree's headers handler, asserting served header values. Both deploy colours are adapted and checked; `base-uri`/`form-action` asserted explicitly; `img-src` checked for bare-scheme widening by token; `X-Frame-Options` pinned as a served header on every route. One assertion stays textual and says why in its docstring: `flip_caddy.sh` hardcodes `cd /opt/vfic` and reloads a live edge, so executing it from a test would mutate the droplet.
- Verified end state: all 5 backend files the card names have zero `?raw` imports, and `grep -rln '?raw' backend/tests/` returns nothing. 56 tests across the five frontend specs, 19 of 19 mutations caught.
- **The class is not fully retired.** Three frontend pins outside the card's 14 survive — see §7.4.

I could not reconstruct the exact per-pass file tally from the commits alone; `758243d4` is the only commit that states its own shortfall, and the "7 of 14" figure is the lead's account of pass 1. What I can verify is the total set and the fact that the shortfall was disclosed in-commit rather than papered over.

---

## 4. Defects found during this sweep

Ordered by how much they matter.

### D0 — The release gate did not pass, and this sweep broke it — **found, then fixed in `ca7be4d8`**

| | |
|---|---|
| **Severity** | High — the repo's own `make release-check` was red, and the sweep is what turned it red |
| **What** | `Makefile:51-53` greps `docs/ops/deployment-guide.md` for the live `alembic heads` value. At `79a2b6a8` that file still read `**HEAD:** \`0056_project_external_api\``, while `alembic heads` was `0057_drop_match_memories_vector_overload` |
| **How found** | This report's author ran the gate line verbatim at `79a2b6a8`. Output: `GATE FAIL` |
| **Proof it is this sweep's** | `git log --diff-filter=A -- backend/alembic/versions/0057_drop_match_memories_vector_overload.py` → `0eaf8b5c perf(retrieval): cast the memories query to halfvec`. PERF-17's commit added the revision and did not update the doc. Before `0eaf8b5c` the head was 0056 and the doc matched, so the gate passed at the sweep base |
| **Why the sweep did not catch it** | The lead's verified runs were `ruff check`, `alembic heads`, typecheck, lint, registry:check, and the two test lanes. None of those is the `release-check` target, and `Makefile:47` would have refused to run it anyway with a dirty tree. The one gate line that fails is the one nobody invoked |
| **Fixed** | **`ca7be4d8`**, applied by the lead immediately after this report surfaced it. One line at `docs/ops/deployment-guide.md:245`, plus a short note on what `0057` does — the migration drops the unused `match_memories(vector, integer, jsonb)` overload so the memories retrieval path resolves to the `halfvec` signature and uses `memories_embedding_halfvec_hnsw_idx`, and its downgrade restores the vector overload verbatim |
| **Verified after the fix** | Replayed verbatim at `e3bd9177`: `DOCS DRIFT GATE: PASS`, `SINGLE HEAD: PASS`, `HEAD_REV=0057_drop_match_memories_vector_overload`. `ruff check .` still `All checks passed!` |
| **Attribution** | The **sweep** introduced the drift. The **review of this report** caught it. The **lead** fixed it. The card was never needed — a one-line doc edit is not a migration edit, so it was never approval-gated, and the only reason it survived is that nobody ran the gate |
| **Why it stays in this report** | A completion report that says "everything passed" and hides the fact that the sweep itself red-lit the release gate is worth less than one that names it. This is the entry that makes the gate's own coverage visible: the gate **did** catch a real drift (of the docs kind) — it just ran after the fact |

### D1 — The rate limiter locked out the client it was protecting (introduced by this sweep, then caught)

| | |
|---|---|
| **Severity** | High, and it sat on the auth path |
| **What** | REL-11's card asked for a TTL that can never go missing. The first implementation (`786ca8bd`) fixed the original INCR/EXPIRE race by re-arming the window on **every** increment. That introduced a worse defect: **a client being 429'd extended its own lockout on every rejected request**, so hammering a locked-out bucket kept it locked out indefinitely, with no recovery short of an operator deleting the Redis key. A rare stranded key became a permanent one — and this is the login limiter, on the module whose own docstring says auth must stay available |
| **How found** | The separate review pass, reading `786ca8bd` against the card's stated invariant |
| **Fixed** | `d2cab403`. The counter and the TTL are now established by a **single Redis Lua script** (`ratelimit.py:82`, `await redis.eval(_BUCKET_INCREMENT, 1, key, window)`), which runs to completion without interleaving — no "connection dropped between INCR and EXPIRE" state is expressible. **The window is armed only when the counter is new**, so a rejection never extends it. The suite was rewritten around the invariants, and each Redis double now exposes only the surface the limiter actually uses, so a future command surfaces as an `AttributeError` rather than as an unexercised path |
| **Proof, not assertion** | Mutation-verified both ways: reverting the double to re-arm-every-increment fails 4 tests; reverting production to the two-command form fails 5. Both were passing before the change |
| **The trap that was almost taken** | The earlier commit had rejected Lua on the grounds that the test doubles did not implement `eval`. That rejection was **correct**, and the commit says so: `eval` would have raised into the fail-open handler and silently converted four existing 429 assertions into passes. The doubles were updated instead of the decision being re-litigated |

Current `backend/app/core/ratelimit.py` is 153 lines; the Lua arming is at `:82`.

### D2 — ARCH-22 routed `.xlsx` through a dependency that is not installed

| | |
|---|---|
| **Severity** | High — a latent 500 on the legacy upload path, shipped by this sweep and masked by a test that could not run |
| **What** | Two defects in one. The extraction owner routed legacy `upload_bytes` `.xlsx` through `openpyxl` while still recording `extraction='utf8_decode'`, so the provenance field named a mechanism that was not the one used. And `openpyxl` is **neither declared in `pyproject.toml` nor installed** — verified: `grep -rn "openpyxl" backend --include=*.py --include=*.toml` (excluding `.venv`) returns only two comment lines in `tests/test_knowledge_pipeline.py:117-118`. A `.xlsx` upload through the legacy route raised `ModuleNotFoundError` and returned 500 |
| **How found** | The review pass. The `.xlsx` test was `importorskip("openpyxl")`, so it silently never ran and could not have caught either defect |
| **Fixed** | `1fa81c0b`. Provenance can no longer drift from dispatch: one table maps format → parser *and* format → provenance, and both the extractor and the recorded value read from it; the release path, which previously wrote `source_file` with no `extraction` key at all, now records the mechanism too. XLSX is read with the **standard library** rather than by adding a dependency to a hot path: `sharedStrings`, `workbook`+`rels` sheet ordering, cell refs so empty cells keep their column, inline/bool/string types, and `styles.xml` number formats so a date serial ingests as `2024-01-01` rather than `45292`. Formulas ingest their cached result, matching the previous `data_only=True` path. A structurally broken workbook is refused with 422 instead of being decoded as text and chunked |
| **Tests** | 12 new, including the exact regression (`.xlsx` must not record `utf8_decode`), the counterweight (`txt`/`md`/`csv` must), column-gap alignment, date-formatted cells, and a drift guard parametrized over **every** format so the two parsed formats can never collide on one provenance value |

### D3 — The schema-restore safety net in the integration conftest had never worked

| | |
|---|---|
| **Severity** | Medium — the net existed and silently did nothing, and it exists specifically to contain the failure it cannot catch |
| **What** | `_restore_head_after_schema_tests` called `_run_alembic(integration_database, "upgrade", "head")`. `_run_alembic` takes **only** the database and already runs `upgrade head` internally (`backend/tests/integration/conftest.py:70`). Every invocation raised `TypeError`, so the guard that restores the shared integration database after a schema-touching test **never restored anything** |
| **How found** | Isolating the PERF-17 halfvec downgrade-symmetry walk onto a throwaway database, which surfaced that the isolation fix depended on a broken net |
| **Fixed** | `911bfdb5`, one line, plus a comment that says why: the call is now `_run_alembic(integration_database)` (`conftest.py:251`). The same commit moved the halfvec walk off the SESSION-scoped shared DB onto a throwaway database via the repo's existing `_roundtrip_database` helper, and added an assertion of the shared database's revision and overload set after **every** alembic step so contamination fails loudly at the step that caused it. Verified by mutating the test back to its old shape — the shared-state assertion caught it on the first step |
| **Note** | This whole area is the integration lane, so none of it runs under the default gate's `-m 'not integration'`. See §7.2 |

### D4 — The rate limiter's documented behaviour was stale in two places

| | |
|---|---|
| **Severity** | Low, but it is the kind of lie that outlives the code |
| **What** | The config comment and the `rate_limits` module docstring both still described a **"fixed window"** after the limiter became rolling |
| **How found** | The review pass, while checking REL-11 |
| **Fixed** | `911bfdb5`. Both now state the invariant rather than the mechanism — *a bucket admits at most `limit` requests per `window` seconds, and a rejected request never extends that window* — so they stay true if the implementation changes again. No default, type or name moved. `external_api_core.py` genuinely is still fixed-window and was deliberately left alone |

### D5 — The compose and coverage-ratchet tests could not fail

| | |
|---|---|
| **Severity** | High as a class — these were the tests standing between the sweep and its own regressions |
| **What** | Every test in `test_compose_service_contracts.py` and `test_coverage_ratchet.py` asserted on the *text* of a config file rather than on what the config does. Proven, not asserted: a fully literal `redis://:user:pw@redis:6379/0` placed into a worker command **left the credential-leak tests green**, because they searched for the string `${REDIS_URL}` rather than for a credential value. The ratchet test passed at `fail_under = 1`. A caddy healthcheck probe naming a port nginx never binds was not caught; dropping `308` from the accepted status set was not caught |
| **How found** | The review pass, by mutation |
| **Fixed** | `55dd322e`. The compose tests now read the container model `docker compose config` produces — variables interpolated, `env_file` folded in, `$$` resolved to the literal `$` the container sees. The credential test compares **every argv element** to the credential values the service was actually given. The worker test runs rq's own `get_redis_from_config` in a subprocess whose environment is exactly the rendered service environment, so deleting `env_file` makes it resolve to localhost and go red. The frontend probe test compares the probe's parsed port against the ports the service actually exposes. A new file (`test_compose_probe_runtime.py`, +350) executes the rendered probes against listeners whose status the test chooses. The ratchet test pins the actual configured floor instead of `0 < floor <= 100`, and measures a real scratch tree with the shipped `.coveragerc` in a subprocess rather than reading `config.source` |
| **Kept, with a reason** | The one sound test in the compose file — that every healthcheck declares the timing keys docker requires — was kept. It is a genuine completeness check; it was just not the whole file |

### D6 — A test asserted on a file's text, and a constant window made a re-arm invisible

| | |
|---|---|
| **Severity** | Medium — this is the assertion that would have caught D1 and could not |
| **What** | After the limiter became a fixed-width sliding window, the window value is **constant**, so a re-arm writes the same number back. A test that read the stored TTL and compared it to the window could not distinguish "armed on the first hit" from "re-armed on every hit" — including from the self-lockout bug D1 |
| **How found** | The review pass, while rewriting the suite for `d2cab403` |
| **Fixed** | `d2cab403`. The Redis double now **counts arming operations** rather than comparing TTL values, so the re-arm is observable |

### D7 — The reviewer's SEC-11 claim

Partly wrong, and nothing to fix because nothing was broken. Full reasoning in §6. The
disagreement was with the *characterisation* of the change, not with the change itself.

### Finding count

The lead's account is that a separate review pass found seven: five fixed, one partly wrong, one
out of scope. I trace the dispositions below and report **eight** rows, because two of the lead's
items are one commit's two separate changes:

| Disposition | Items |
|---|---|
| Fixed | D1, D2, D3, D4, D5, D6 — six |
| Partly wrong (nothing to fix) | D7 / SEC-11 |
| Out of scope | OPS-28 / §5.1 |
| **Found outside that review pass — and now fixed** | **D0, the release gate this sweep had broken.** Caught by writing this report, fixed by the lead in `ca7be4d8`, verified by replaying both gate lines at `e3bd9177` |
| **Found outside that review pass — and still open** | **DOC-19, the deleted repository constitution** (§5.5). Found by writing this report; recorded as a card in `e3bd9177`, deliberately not fixed |

Net: **two release-blocking defects were introduced by this sweep, and both were found** — one
(`d2cab403`'s self-lockout, D1) by the review pass, one (D0) by the writing of this report. One
high-severity latent defect was introduced and found (D2). Two remain open by decision, not by
oversight: OPS-28 and DOC-19.

---

## 5. Defects found and NOT fixed

### 5.1 OPS-28 — the migration chain cannot reach base

`kanban/TODO/20260927_OPS-28-the-migration-chain-cannot-reach-base-0006-downgrade-drops-publis.md`
(`status: todo`, `severity: high`). Committed as a card in `89758aaf`. **Deliberately left open.**

`alembic downgrade base` cannot complete. The chain applies forward cleanly to head, but the
reverse walk dies between 0006 and 0005 because two revisions disagree about the `knowledge_status`
enum:

- `alembic/versions/0006_publish_knowledge_status.py:96-136` — the downgrade converts
  `knowledge_status` back to the pre-`PUBLISHED` value set (`READY_FOR_REVIEW`, `APPROVED`,
  `REJECTED`, …), which does **not** include `PUBLISHED`.
- `alembic/versions/0005_remove_knowledge_approval_gate.py:51` — the downgrade re-creates
  `public.documents` with a `WHERE kd.status = 'PUBLISHED'` predicate, naming a label that no
  longer exists at that point in the reverse walk.

Both files were last written in `dce23c94` (2026-06-27) and `git status backend/alembic/` was clean
at the audited HEAD, so this predates the sweep by three months and is **not** a regression from it.
Verified on a throwaway database (`alembic_chain_tmp_01`, created and dropped; no existing database
touched): `upgrade head` OK at `0057` with exactly one head; `downgrade base` **FAILED**, stopped at
`0005` with `invalid input value for enum knowledge_status: "PUBLISHED" … WHERE kd.status = 'PUBLISHED'`;
`upgrade head` from that partial state OK again. The database is not bricked — it is also not
reversible.

A second, independent reversibility defect: the offline `alembic downgrade head:base --sql` preview
dies much earlier, at `alembic/versions/0044_generic_contact_case_kernel.py:465`, with
`AttributeError: 'MockConnection' object has no attribute 'scalar'` — a
`connection.scalar(SELECT EXISTS …)` data guard cannot run in `--sql` mode. So an operator cannot
even *preview* the reverse walk offline. The chain therefore has at least two independent
reversibility defects, not one.

**The release gate cannot see this.** `Makefile:50` checks only that `alembic heads | wc -l` = 1 and
`Makefile:51-53` checks that the docs name it. I confirmed at `e3bd9177` that `alembic heads` reports
exactly one head and both gate lines pass. **The gate is green while the chain is irreversible** —
the same gate whose *doc* check was failing for an unrelated reason until `ca7be4d8` (D0). Fixing the
docs did not make the gate any more able to see this.

**Why not fixed:** migration edits are approval-gated, and a kanban card is not that authorisation.
The card says so itself (`Notes`) and prescribes two unbundled changes plus the missing coverage
(extend `tests/integration/test_migration_roundtrip_walk.py` to base rather than writing a new
harness — and note that test is itself in the excluded integration lane).

### 5.2 `ruff format --check` fails on 320 files

Pre-existing, and **not** in the release gate: `Makefile:54` runs `.venv/bin/ruff check .` only.
Deliberately not fixed rather than turned into a mid-sweep reformat storm — 320 reformatted files
would have made every other diff in this series unreviewable.

**The card's figure is stale.** OPS-28's `Notes` says 306; the observed count at `79a2b6a8` is
**320** ("320 files would be reformatted, 461 files already formatted"). The sweep added files, so
the debt grew by 14 during the sweep it declined to touch.

### 5.3 Prettier deviations — 20 files, not 11

Same reasoning; `npm run prettier` is not in the release gate (`Makefile:55` runs lint, typecheck,
registry:check, tests, coverage, build).

Exact command: `cd frontend && npx prettier --config ./.prettierrc.json --list-different "**/*.{mjs,js,json,ts,tsx,css,md,html}"` → **20 files**. The lead's figure of 11 is not reproducible at HEAD.

Two things worth knowing rather than glossing:

- **9 of the 20 were touched by this sweep** (`responsive-workspace-layout.test.tsx`,
  `settings-workspace-layout.test.tsx`, `SettingsConsolePage.tsx`, `tailkit-action-sizing.test.tsx`,
  `performance-trend-layers.test.tsx`, `persona-layout-regressions.test.tsx`,
  `projects-workspace-layout.test.tsx`, `vietnameseCrmMessages.test.ts`,
  `account-layout-regressions.test.tsx`). The sweep left files it had just rewritten in a
  non-prettier shape. Whether they were already deviant at the sweep base, I did not verify.
- **The sweep fixed one**: `0a33186c` formatted `scripts/generate-registry.mjs`, and
  `npx prettier --check scripts/generate-registry.mjs` now reports "All matched files use Prettier
  code style!".

### 5.4 The residual redis argv exposure, and where the card's prescribed fix was wrong

`backend/docker-compose.yml:95` still reads:

```
- exec redis-server --appendonly yes --requirepass "$$REDIS_PASSWORD" --maxmemory 256mb --maxmemory-policy volatile-lru
```

At the sweep base (`git show b33c3c97~1:backend/docker-compose.yml:84`) this was
`command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD:?set REDIS_PASSWORD in .env}", …]`
— the `${…}` was **interpolated by compose**, so the literal secret was written into
`docker inspect`'s `Config.Cmd`. SEC-11 changed it to `exec … "$$REDIS_PASSWORD"`, which defers to
the container's shell.

**What that does and does not buy.** The secret is no longer in the compose file or in
`docker inspect`. It **is** still a process argument to `redis-server` inside the container, so it
is visible in `docker top`, in `/proc/*/cmdline`, and to anything that can read the container's PID
namespace. `redis-server --requirepass` has no environment-only equivalent; the fix would be a
generated config file with restrictive permissions, which is a compose-structure change beyond this
card.

**The card's count was right; its prescribed fix was not.** SEC-11's title names "four compose
services **and the redis healthcheck**", and that is exactly what was there: four
`--url ${REDIS_URL}` argv entries (`worker-ingest`, `scheduler`, `worker-followup`,
`worker-maintenance`) plus `redis-cli -a ${REDIS_PASSWORD}` in the redis healthcheck. Five argv
sites, all five fixed.

What the card got wrong was its remedy. Its `Suggested fix` says "rq **and rqscheduler** default to
the REDIS_URL environment variable, which env_file already provides". That is false for
`rqscheduler`: its `--url` flag defaults from `RQ_REDIS_URL` and otherwise falls back to
host/port/db/password, i.e. localhost. Following the card literally would have removed `--url` from
`scheduler` and **silently disconnected the scheduler from the broker**. The sweep diverged from the
card's prescription on that one service — see §6.3.

The card also does not mention `redis-server --requirepass` at all. That is the item above, and it
is the one real remaining argv exposure.

### 5.5 DOC-19 — the repository constitution was deleted and nothing routes around it

`kanban/TODO/20260927_DOC-19-restore-or-redirect-the-repository-constitution-deleted-in-65069078.md`
(`status: todo`, `severity: high`). Opened as a card in `e3bd9177`. **Deliberately left open.**

**What it records.** `AGENTS.md` and the entire `standards/` directory were deleted in `65069078`
("Refactor codebase: Remove unused types, delete outdated standards documents, and streamline
performance guidelines"). The file every coding agent loads first — `.claude/CLAUDE.md` — still
routes to all of them, so an agent following the instructions is sent to four documents that do not
exist. Verified absent at `e3bd9177`: `AGENTS.md`, `standards/agent-completion-checklist.md`,
`standards/definition-of-done.md`, `standards/review-checklist.md`.

**What is now unstated, and it is not cosmetic.** `AGENTS.md` was the binding contract. With it
gone the repo has no stated architecture rule, **no approval-gated path list** (migrations,
webhooks, auth, bot prompts/safety, dependency changes, deployment files), **no secrets rule**, and
**no completion contract**. The owner granted blanket approval for this sweep, but that was a
one-off decision, not a durable rule — and it is now the only record that those paths are sensitive.

**The concrete evidence is in this report.** I had to reconstruct the 16-gate checklist from the
previous sweep's completion report, because the checklist file itself was gone. That reconstruction
is noted in the *Premises* section above and is exactly the failure mode in miniature: the gate list
now lives only in whichever report happened to be written most recently.

**Why not fixed.** Restoring or rewriting the repo's constitution is an owner decision about how
this project is governed, not a documentation edit — the same class as OPS-28's "a card is not that
authorisation." The card carries the recovery command (`git show 65069078^:AGENTS.md`) and asks for
a **link check** asserting that every path named in `.claude/CLAUDE.md` exists, failing the release
gate when one does not. That step matters more than the restore decision: it is the same class as
the Alembic docs-drift gate that *did* catch a real drift during this sweep (D0), and the repo
already has the pattern to copy.

One point the card raises that I can corroborate: `65069078` says "delete outdated standards
documents", which suggests the content was believed stale, but the sweep's own card history shows
several of those documents were *recently corrected* — DOC-14 through DOC-18 fixed stale claims in
exactly these files days before they were deleted. Whether anything of value was lost is
unverified.

---

## 6. A reviewer claim the lead rejected

**The claim:** SEC-11 had merely "moved the secret from Cmd to Env rather than removing it."

**The lead's rejection: the claim is not right.** Verified both halves:

1. **`REDIS_URL` was in both places before the change, and the change removed it from argv.**
   At the sweep base, `worker-ingest` read
   `command: ["rq", "worker", "ingest", "--url", "${REDIS_URL}"]` **and** carried `env_file: .env`,
   which supplies `REDIS_URL` (`.env.example:31` → `REDIS_URL=redis://redis:6379/0`). At HEAD
   (`docker-compose.yml:258-270`) the service keeps `env_file: .env` and the command is
   `["rq", "worker", "ingest"]` — the argv occurrence is gone. Nothing was moved into Env that was
   not already in Env.

2. **The residual Env exposure is inherent to `env_file` and pre-dates the sweep.** The service has
   to learn the broker URL somehow; `env_file` is how this compose file has always supplied it, for
   the backend workers (`command: ["python", "-m", "app.workers.run_worker", …]`, which never had a
   `--url` flag at all). SEC-11 did not create the Env channel. It removed the *duplicate*.

3. **The scheduler case proves the reviewer's framing is backwards.** `rqscheduler` does **not** read
   `REDIS_URL` — its `--url` defaults from `RQ_REDIS_URL` and otherwise falls back to
   host/port/db/password, i.e. localhost (`docker-compose.yml:292-298`). So removing `--url` there
   *without* adding `RQ_REDIS_URL` would have silently disconnected the scheduler from the broker.
   The change had to add the Env variable, and it added it **for the scheduler only**, as a
   documented consequence of the argv removal — not as the removal method.

Why the rejection is recorded rather than just asserted: a reader who takes the reviewer's stronger
claim at face value will conclude SEC-11 shipped no security improvement at all, and may reopen the
argv exposure. It did ship one, it shipped five changes, and it shipped a regression risk (the
scheduler) that it handled correctly.

The one part of the reviewer's claim that is fair: a **residual** exposure exists, and it is not
zero. Two things remain, and neither is what the reviewer described. The broker URL is in the
container's *environment* — inherent to `env_file`, pre-dating the sweep, and unavoidable
(`docker-compose.yml:84-104` names it in place). Separately, `redis-server --requirepass` is still a
process argument *inside* the container (§5.4) — an argv exposure the reviewer did not mention and
which the card never asked about.

---

## 7. Residual risk in what shipped

### 7.1 The runtime-surface boundary guard is a whole-`app/`-tree hash, and it got blunter

`backend/tests/test_runtime_surface_inventory.py` is a whole-tree AST scan whose result is compared
against `EXPECTED_BROAD_BOUNDARY_COUNTS` plus a SHA-256 digest. It is the guard that catches an
unreviewed provider call site. It works by classifying calls: `provider_boundary` counts a `send_*`
call anywhere, **and** any of a fixed verb set (`get`, `getdel`, `post`, `put`, `patch`, `delete`,
`request`, `eval`) inside a file that carries a `get_http_client` / `httpx` marker
(`test_runtime_surface_inventory.py:384-386`).

**`provider_boundary` moved 92 → 87.** Verified by walking the value across the series: 92 at
`b33c3c97~1`, `08003ea4`, `786ca8bd`, `14ddcabb`, `21ac7cb9`, `0eaf8b5c`, `bd0fd052`, `d9018544`,
`14d61246`, `d2cab403`; **87** from `e6ea7810` onward. The change is in `e6ea7810`, caused by
ARCH-21's `clients.py` split in `d9018544`.

**Cause, and it is exactly as unflattering as it sounds.** `clients.py` carried the
`get_http_client` marker only because the embedder lived there. Moving the embedder to
`graph/embedders.py` left `clients.py` without the marker, so every dict `.get` in the agent loop
(`agent`, `agent._dispatch_one`, `direct`), the provider default lookup `_active_llm_provider` (now
`providers.py`), and the finish-reason reads `_answer_was_cut` (now `answer_repair.py`) **stopped
being scanned as egress**. Five reviewed rows went away. This is documented in the test file at
`:156-166`.

**The defence, stated honestly.** The argument that this is a net improvement is that those rows
were heuristic false positives — `dict.get` is not egress — and that `graph/embedders.py` is still a
provider-transport file, so the one real egress site (`OpenRouterEmbedder.batch`'s `client.post` plus
its three response reads) remains under the same two reviewed rows. Two facts support it: the
`EXPECTED_BROAD_BOUNDARY_COUNTS` diff in `e6ea7810` touches **only** the `provider_boundary` line —
every other category count is unchanged — and the explicit inventory fixture was regenerated and
matches.

**The risk, stated just as honestly.** The guard is now **less sensitive to those sites**, and that
happened as a by-product of a refactor rather than as a decision. A future `.get` on a dict in
`app/graph/agents.py` or `app/services/retrieval/` is no longer surfaced for review even if it is
touched. This is a detection regression the sweep introduced and did not flag as such, and it is the
single change in this series most likely to be missed by a reviewer skimming for behaviour changes.

### 7.2 The integration lane is excluded from the release gate, and did not fully run

Two files carry the **only** coverage of behaviour this sweep shipped:

- `backend/tests/integration/test_memories_halfvec_index_migration.py` — the halfvec index selection
  that PERF-17 exists to enable.
- `backend/tests/integration/test_chatops_followup_calendar.py` — the ICT followup calendar (REL-9)
  and the optimistic-apply `ConflictError` path (REL-10).

Both live in `tests/integration/`, and `Makefile:54` runs `pytest -m "not integration"`.
**Neither runs in the release gate.** They must be invoked deliberately.

**What was actually run** *(lead, final)*. The sweep-relevant subset was run deliberately:
`test_memories_halfvec_index_migration.py`, `test_chatops_followup_calendar.py`,
`test_smoke_turn_invariant.py`, `test_turn_pipeline_check.py` → **17 passed in 92.56 s**. That
clears the gap this report first flagged — the `ConflictError` path is now covered by a run, not
just by an assertion on the page.

**What was NOT run, stated plainly.** The **full integration lane did not complete.** It exceeded
the 300 s harness cap twice, and `test_migration_roundtrip_walk.py` alone takes ~342 s, so it was
not run to completion. Treat the integration lane as an **unverified area**, not a green one. The
two cap-truncations mean it is not even known how much of the lane ran.

That same exclusion is why the following are unverified: the entire `_restore_head_after_schema_tests`
guard, the `_roundtrip_database` isolation, and the halfvec downgrade-symmetry walk (D3) — all in
the excluded lane. And it is why OPS-28 cannot be caught by the gate: the test that would catch it,
`test_migration_roundtrip_walk.py`, is both the slowest test in the repo and excluded. The card's
own `Suggested fix` says so — "if the reverse walk is meant to be enforced, the gate has to invoke
it". The 300 s cap and the `-m "not integration"` filter are the same problem seen from two sides:
the lane that would prove the migrations are reversible is the one lane nobody runs to completion.

### 7.3 The frontend `@theme` tokens cannot be asserted above 767px

Tailwind is not processed in the `app` vitest project, so the daisyUI / `@theme` scale is not emitted
and `var(--fs-*)` / `var(--crm-fs-*)` / `var(--fw-bold)` are unresolvable above 767px. Four suites
document this and each states **which different property it asserts instead**:

| Suite | Tokens named as unassertable | What is asserted instead |
|---|---|---|
| `projects/projects-workspace-layout.test.tsx:19-25` | `var(--fs-page-title)`, `var(--fs-body-sm)` | the layout the rules sit inside — a page title that is **not the browser default**, and a create button whose box the console actually paints. `--border` resolves from `:root`, so the frame/flat-surface assertions are real painted values |
| `personas/persona-layout-regressions.test.tsx:23-29` | every `var(--fs-*)` and `var(--crm-fs-*)` | **the measured height** — which proves the rule's *other* declarations survive. `--surface-solid` / `--border` do resolve, so the flat-plane colour and frame assertions are real |
| `conversations/inbox/responsive-workspace-layout.test.tsx:22-30` | `var(--fs-page-title)`, `var(--crm-fs-title-lg)` | the desktop font size is asserted **only below 768px**, where `--text-page-title: 1.375rem` is set directly on `:root` and resolves to 22px; the mobile title block is asserted at phone width where `--crm-fs-title-lg` also resolves |
| `performance/performance-trend-layers.test.tsx:25-31` | `var(--fs-page-title)`, `var(--fs-body-sm)`, `var(--fw-bold)` | the mobile block is inside 720px, where `--fs-page-title` resolves to 22px, so those are asserted **there**. `--border` / `--card` / `--muted-foreground` resolve from `:root`, so frame, fill and shadow are real |

So a type-only regression in any `@theme`-backed rule above 767px would not fail the suite. This is
a real hole, it is honestly documented in each file, and it is a property of the test lane, not of
this sweep — the sweep converted the assertions it could convert and said which ones it could not.

One more lane fact that matters for reading those files: `page.viewport()` drops `:root` custom
properties, so every token is read off the rendered element via
`getComputedStyle(element)`, never off `documentElement`
(`responsive-workspace-layout.test.tsx:28-30`).

### 7.4 Source-text pins the TEST-17 card did not name — one is being converted now

`grep -rln '?raw' frontend/src` returns ten files. Seven of them are the converted layout specs,
where the hit is **prose in the header comment** explaining the conversion, not a live pin. The
three genuine remaining source-text reads outside the card's 14 files:

- `capabilities/kernel/index.test.ts:54,77-81` — imports `./components.tsx?raw` and asserts
  `not.toContain(...)`, `not.toContain("<Suspense fallback={null}>")`,
  `toContain('role="status"')`. This is the **highest-coverage-gated file in the repo** (one of the
  three 80 % per-file floors in `vitest.config.ts:35-39`). **Status: conversion IN PROGRESS,
  confirmed in the working tree.** `git status --short` at `e3bd9177` shows both
  `capabilities/kernel/index.test.ts` **and** `capabilities/kernel/components.tsx` modified and
  neither committed — the test and the module it was reading, which is the right pair to change
  together. I did not read or judge the in-flight diff; it is a sibling's half-finished work and
  this report only records that it is happening. A reviewer must confirm three things when it
  lands: the `?raw` import is gone, the three behaviours the old text assertions stood in for are
  still pinned behaviourally, and the 80 % per-file floor still holds.
- `css-scoping.test.ts:4-7` — `import.meta.glob(..., query: "?raw")` over every stylesheet under
  `atomic-crm/`. The card's own `Suggested fix` treats this file as the legitimate home for
  genuinely-global rules ("fold … into the existing css-scoping ratchet"), so its survival is
  intended, not a gap.
- `providers/rest/dataProvider.test.ts:5` — imports `resource-paths.json?raw`. Asserting a
  generated resource table's contents is a defensible use of `?raw`; not flagged as a defect.

The kernel one was the real finding: TEST-17's scope did not include it and it is not a regression
from this sweep (the file was untouched through `79a2b6a8` — `git log b33c3c97~1..HEAD -- <path>`
was empty). A card titled "retire the raw-source assertion tail" was not fully delivered while a
source-text pin lived on the repo's most heavily gated component. That gap is now being closed.

### 7.5 Smaller, but real

- **The working tree is dirty**, so `make release-check` refuses to start at all
  (`Makefile:47`). ` M .claude/CLAUDE.md`, Repowise's own auto-update. It is not a source change,
  but it will block the gate until it is committed or reverted, and it will recur.
- **ARCH-27 moved historical dashboard numbers.** Dropping `faq_bypass_ms` from `_MEASURED_STAGES`
  means a row recorded before the removal now has that time counted as *unmeasured dark time*
  rather than silently subtracted. The commit calls this the correct outcome and pins the new
  arithmetic in both directions, but it **does** move historical dashboard numbers, and a reader
  comparing pre- and post-`6a434f8e` charts will see a discontinuity that is not a regression.
- **The direct-context persona now fails soft to `persona.md` on a read error**
  (`14d61246`, ARCH-28). Deliberate, flagged in the commit, and a behaviour change nobody asked
  for: a persona read error is now invisible rather than loud.

---

## 8. What a reviewer should check first, in priority order

1. **The in-flight `capabilities/kernel/index.test.ts` conversion** (§7.4). An agent is rewriting
   the last live source-text pin, in the file that carries one of the repo's three 80 % per-file
   coverage floors. Confirm the conversion landed, that it still pins the three behaviours the
   `?raw` assertions stood in for (`not.toContain(...)`, `not.toContain("<Suspense
   fallback={null}>")`, `toContain('role="status"')`), and that the 80 % floor still holds
   afterwards. This is the only in-flight item in the sweep and the only place a behavioural rewrite
   is likely to move a coverage number.
2. **`backend/app/core/ratelimit.py` — the whole file, read as if you were the client being
   429'd.** The shipped design is a single Lua script that arms only on a new counter. The defect
   this sweep introduced and fixed (`d2cab403`) was that a rejected request extended its own
   lockout. Confirm the invariant "a rejected request never extends that window" actually holds,
   and confirm the test doubles cannot silently accept a future `redis` command
   (`d2cab403` narrows each double to only the surface the limiter uses — that narrowing is
   load-bearing, not incidental).
3. **`backend/app/services/knowledge/file_extraction.py` (ARCH-22) — the xlsx path.** Verify the
   stdlib reader against a real workbook, not just the 12 tests: a date-formatted cell, a column
   gap, a formula's cached result, a broken zip. The previous implementation used a dependency that
   was never installed, and the test that would have caught it was an `importorskip` that never ran.
   Also check the provenance drift guard is parametrized over *every* format, not just the two the
   review looked at.
4. **`backend/tests/test_runtime_surface_inventory.py:156-166` and the 92 → 87 change** (§7.1).
   Decide whether losing the agent-loop dict-`.get` rows is acceptable detection loss. If not, the
   fix is to make the provider-transport marker explicit per module rather than marker-based, which
   is a real change to the guard's design. Nothing in the release gate will tell you either way.
5. **The integration lane, and specifically `test_migration_roundtrip_walk.py`** (§7.2). The
   sweep-relevant subset is green (17 passed in 92.56 s), but the **full lane did not complete** —
   it blew the 300 s harness cap twice and this one test alone takes ~342 s. It is the test that
   would prove the migration chain reverses, and it is both the slowest test in the repo and
   excluded by `-m "not integration"`. Run it with a raised cap. This is the highest-value
   unverified area in the sweep.
6. **`d2cab403`'s mutation evidence.** The claim "reverting production to the two-command form fails
   5 tests, reverting the double fails 4" is the strongest single piece of evidence in the sweep.
   Re-run those two mutations. If the numbers do not reproduce, the rewrite's assurance is
   overstated and the rest of the suite's mutation claims need re-checking.
7. **The two open cards, in severity order.** **OPS-28** (§5.1) — decide whether the chain's
   irreversibility is acceptable while the blue/green flip is the only rollback mechanism. This is
   an owner decision with an incident-shaped failure mode. **DOC-19** (§5.5) — the repo currently
   has no stated approval gate, no secrets rule, and no completion contract. The link check the card
   asks for is the part that matters most and the part that is cheapest.
8. **The two judgement calls in §3 that changed scope rather than closed it.** FE-22 chose flatten
   over certify, which accepts four pre-existing unenforced outward edges rather than fixing them —
   read the module comment at `integrations/index.tsx`, which names those edges and records the bar
   for re-introducing layer directories. SEC-9 is an accepted risk on a candidate-facing revenue
   channel, with four named re-decision triggers; trigger 1 (a prompt-injection incident reaching a
   candidate through KB content) would convert it from accepted risk to a live defect.

**No longer on this list:** `docs/ops/deployment-guide.md:245`. It was priority 1 when this report
was first drafted, because the release gate was red because of it. Fixed in `ca7be4d8`, both gate
lines replay green at `e3bd9177`. It stays in §4 D0 because the finding is worth more than the fix.

Lower priority but worth a glance: the 20 prettier deviations, 9 of them in files this sweep
rewrote (§5.3), and the 320 ruff-format files (§5.2). Neither is in the gate; both are cheap to
fix in one standalone commit that is not this series.
