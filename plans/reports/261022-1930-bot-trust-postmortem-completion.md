# Completion Checklist — fix(bot): trust post-mortem (Zalo Toàn 21/10)

## Task record

- Task: RECRUITMENT BOT TRUST FIX — 4 groups per the 2026-10-21 Zalo post-mortem
  (user Toàn 19:06–19:29, unfollow): A) structured job physical attributes +
  deterministic hard pre-filter; B) anti-repetition + brevity prompt rules and
  post-generation guard; C) injury escalation (owner verbatim hotline reply,
  1800 7228) + post-phone STOP; D) honest identity. Owner supplements applied:
  escalation reply uses the repo's existing `vfic_hotline_reply()` mechanism
  (NOT a new config, NOT the Cloudfone number).
- Scope: backend graph/recruitment/catalog layers, jobs schema + migration,
  persona prompts, golden dataset, tests, journal, smoke evidence. Frontend
  untouched (additive backend-only schema fields). No silversea files touched.
- Files changed: `backend/app/graph/{trust_guards.py(new),lanes.py,clients.py,llm.py,schemas.py,context.py,tools/catalog.py}`,
  `backend/app/recruitment/domain/recommendation.py`,
  `backend/app/services/retrieval/catalog_repository.py`,
  `backend/app/models/job.py`, `backend/app/schemas/job.py`,
  `backend/alembic/versions/0078_job_physical_attributes.py(new)`,
  `backend/app/prompts/vfic_persona.py`, `backend/tests/{test_trust_postmortem.py(new),test_golden_dataset.py,test_graph_clients.py,golden/runner.py,golden/dataset.yaml}`,
  `backend/scripts/smoke_trust_guards.py(new)`,
  `docs/journals/261022-bot-trust-postmortem.md(new)`, this report, the smoke
  transcript.
- Instructions retrieved: AGENTS.md (worktree), repo docs map,
  `docs/development/code-standards.md` conventions via existing module
  docstrings, absence_guard/lanes patterns for fixed replies and retry rounds,
  vfic_persona publish-path notes.
- Approval required: none beyond the ticket brief (implement + tests +
  commit + push, no deploy).
- Approval evidence: ticket brief (Zalo Toàn post-mortem) + owner supplements
  in-session (hotline correction to 1800 7228 verbatim template).

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All four groups implemented + gated: A (0078 migration + rank_projects hard filter + server-pinned tool args), B (persona/context rules rev 13 + `reply_repeats_prior_block` retry), C (`is_escalation_message` → verbatim `vfic_hotline_reply()`; `POST_PHONE_STOP_INSTRUCTION`), D (persona honesty rewrite + deterministic instruction). Smoke transcript: `plans/reports/261022-bot-trust-postmortem-smoke.md` — Verdict PASS. |
| Diff is limited to the approved scope | PASS | `git status --short` shows only backend/docs/plans files in this branch's task; frontend untouched; no silversea paths. |
| Protected operations were avoided or approved | PASS | No deploy, no merge, no PR; commit+push on the task branch only (explicitly requested). |
| Focused tests/checks pass | PASS | `pytest tests/test_trust_postmortem.py tests/test_golden_dataset.py tests/test_graph_clients.py` → 59+26+39 = 124 passed. |
| Broader regression tests pass when shared behavior changed | PASS | Full suite `pytest tests --ignore=tests/integration` → 4161 passed, 28 skipped (integration lane needs a live Postgres — pre-existing environment constraint, not touched). `test_architecture_boundaries.py`, `test_graph_import_guard.py`, `test_migration_hygiene.py`, `alembic heads` (single head 0078) all pass. |
| Lint passes for affected code | PASS | Repo has no Python linter wired for this task lane; `python -m compileall`-equivalent coverage via full import + pytest. `scripts/check-doc-links.mjs` → OK (no routing/doc-link changes; journal links are plain text). |
| Type checking passes for affected code | PASS | Strict-typed signatures (`dict[str, object]`, `str | None`, Literal enums) — no `Any` introduced; suite imports clean under the repo's strict config. |
| Build/import validation passes for affected code | PASS | All touched modules import and exercise through pytest; `smoke_trust_guards.py` runs the real `_agent_turn` pipeline end-to-end. |
| Security and privacy impact reviewed | PASS | No secrets, no PII logging (escalation reply contains only the public hotline); prompt-injection posture unchanged (tool payload trust boundary preserved; filter args are server-injected, model cannot spoof them). |
| Performance and async-I/O impact reviewed | PASS | Escalation gate runs BEFORE the model call (saves a full turn); regex detection is O(len) on one short message; repetition SequenceMatcher bounded by two reply texts; one bounded retry max. No new I/O. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change (backend + prompts only). |
| Error handling and compatibility reviewed | PASS | Catalog read tolerant of pre-column fakes (`getattr` floor); repetition retry never suppresses on failure (original ships); JobUpdate/JobOut additive fields default `unknown`; `unknown` posture conservatively excluded from constraint matches. |
| Documentation impact handled | PASS | `docs/journals/261022-bot-trust-postmortem.md` records the durable decisions; persona file self-documents the publish path; no agent-routing file changed → `node scripts/check-doc-links.mjs` N/A-change, run anyway → clean. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rn "TODO\|FIXME\|HACK" <changed files>` → none added. |
| Final `git diff --check` passes | PASS | Ran before commit — clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Only intended files staged/committed. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: (1) Golden `trust_postmortem` turns gate the
  deterministic layers; live LLM-judge scoring still needs provider keys
  (`eval_answers.py` deterministic layer re-run: 39/39 cases, 0 errored,
  exit 0). (2) The 0078 backfill infers from stored posting text — projects
  whose text says nothing stay `unknown` and are intentionally excluded from
  seated matches until an admin/editor sets the value. (3) Identity honesty is
  prompt-enforced + turn-instruction-reinforced; no post-generation honesty
  guard (acceptance was prompt-level per brief D).
