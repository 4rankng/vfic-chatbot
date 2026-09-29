# TingTing OA: no human escalation — hotline +84 914 827 988 everywhere

## ADDENDUM — controller review response (2026-09-30; this section's run is the AUTHORITATIVE one)

The controller reviewed an intermediate snapshot and flagged (1) a broken
import and (2) missed owner rulings. What the current tree actually contains:

1. **The cited break (`tools/__init__.py:36` importing the removed
   `TINGTING_VERIFY_EXHAUSTED_REPLY`) does not exist at HEAD or in the
   worktree.** `git show HEAD:backend/app/graph/tools/__init__.py` has no
   such import, the file is unmodified vs HEAD, `import app.graph.tools`
   succeeds, and `pytest --collect-only tests/test_graph_runner_turn.py`
   collects 122 tests. What DID exist was a mid-edit window during the
   expansion: after the guide constants became builders but before
   `tools/tingting_identity.py`'s import of the old constant was updated,
   `import app.graph.tools` failed via that submodule. That window closed
   within the same working session. Honest sequence note: my final
   comment-only edits to lanes.py/tingting_guide.py landed after the last
   full test run of that session — bad discipline; the verification below
   postdates EVERY edit in this tree. Sweeping every importer of the guide
   also surfaced one genuinely missed consumer the focused runs never
   imported: `tests/test_persona.py::test_tingting_support_prompt_excludes_the_recruitment_directory`
   called the new required-kwarg builder without `hotline` — fixed.
2. **The two owner rulings (admin-editable field + seeded value) are
   IMPLEMENTED** — see the scope-expansion section below, which was delivered
   in the same session (setting service + API schema, Alembic 0058 seed,
   turn-time reads with no fallback, frontend field). The controller's review
   quoted this report's ORIGINAL "where the number lives" section, which
   still described the pre-expansion design; that section is now marked
   superseded so the report no longer contradicts itself.
3. **Drift pin moved to the seed, per the ruling:** the only place the
   digits live in source is the Alembic 0058 seed, now pinned by
   `test_the_seed_migration_pins_the_owner_approved_hotline` (loads the
   migration module, asserts the seed value and both guards: upgrade's
   `WHERE NOT EXISTS` — operator edits win — and downgrade's exact-value
   DELETE — admin edits survive). The runner-suite drift guard now documents
   that it pins the BUILDER's formatting with the seed value as input.
   The 18007228 recruitment inline constant stays untouched.

### Authoritative verification (postdates every edit)

- Unit set (runner_turn, tingting_api incl. the seed-pin test,
  verify_exhaustion, proactive_turn, lead_extraction, smoke_turn,
  smoke_turn_progressive, persistence_worker, persona,
  runtime_surface_inventory, deployment_makefile, concurrency):
  **450 passed, 1 failed** — the failure is
  `test_every_http_endpoint_matches_the_reviewed_authority_snapshot`,
  caused by a teammate's in-flight edit to `backend/app/api/projects.py`
  (route count 28 vs snapshot 27; their lane, untouched by me, already
  flagged in the expansion section).
- Integration lane: migration_roundtrip_walk + support_handoff_reply_send +
  extraction_intent_escalation_concurrency → **5 passed in 19:35** — 0058
  survives upgrade→downgrade→upgrade alongside all prior migrations.
- `ruff check .` clean; `uvx pyright app/graph app/services/tingting_api.py
  app/services/integration_settings/providers/tingting.py
  app/schemas/integrations.py scripts/smoke_turn.py` → 0 errors (re-run after
  the last production edit, which had postdated the earlier pyright pass).
- Frontend unchanged since its verification: integrations vitest 58 tests
  green (twice), typecheck clean for my files (the one project-wide error is
  the teammates' projects lane).

---

## SCOPE EXPANSION (same session, controller ruling): the hotline is now an admin-editable setting

The owner clarified that +84 914 827 988 must be SEEDED into the settings
store, not kept as a code fallback: the runtime reads ONLY the stored setting,
and an empty read degrades honestly (never resurrects the number from code).

### Where the setting lives

- Key: `tingting_hotline` (constant `TINGTING_HOTLINE_SETTING`) in the
  existing `integration_settings` table — the same store as the X-API-Key,
  same `TingtingApiService` CRUD surface, same `record_audit` trail
  (`backend/app/services/tingting_api.py`: `hotline()` getter,
  `replace_hotline()` writer mirroring `replace_reset_oa_id`).
- Seeding: new Alembic data migration
  `backend/alembic/versions/0058_tingting_hotline_setting.py` — the repo's
  established data-seed shape (`op.execute(INSERT ...)` like 0004/0012/0047),
  idempotent via a WHERE guard, so operator edits always win. The value is
  stored PLAINTEXT with `is_secret=false`: the cipher's documented fail-soft
  (unprefixed rows pass through) is the sanctioned door for seeded rows, and
  an admin edit later re-seals it as `v1:` ciphertext through the same getter.
  Downgrade deletes the row only while it still holds the seed value.
- API: `GET/PUT /api/v1/integrations/tingting` carry `hotline`
  (`TingtingIntegrationSettingsOut.hotline: str = ""`,
  `TingtingIntegrationSettingsUpdate.hotline: str | None` max_length 32;
  `TingtingSettingsMixin.update_tingting` persists it).
- Turn-time read: `GraphRetrievalPort.tingting_hotline()` →
  `RetrievalRepository.tingting_hotline()` (logs a WARNING when the row is
  empty — the one turn-time flag site). `lanes._tingting_hotline(deps)` reads
  it defensively (same getattr pattern as `tingting_api_configured`) on
  support-OA turns only; the verify tool reads it the same way for the
  exhaustion dictation; the proactive lane reads it for the nudge prompt.

### Copy is now built per turn, not a constant

`tingting_guide.py` gained builders — `tingting_hotline_reply(hotline)`,
`tingting_verify_exhausted_reply(hotline)`, `tingting_support_persona(hotline)`,
`tingting_api_guide(hotline)`, `tingting_api_prompt_block(hotline)`,
`tingting_support_system_prompt(include_guide=, hotline=)` — so the persona,
the guide, and every escalation reply quote the CURRENT stored number. The
builders take no default: an empty/unreadable value renders the honest
no-number sentence "Dạ tình huống này em chưa hỗ trợ được qua tin nhắn ạ." —
the seed guarantees presence; code never resurrects the number. Four
degenerate tool-verdict texts (`_NOT_CONFIGURED`, `_UNREADABLE`, the API-error
state, `_UNREADABLE_RESPONSE`) lost their "để lại số điện thoại để được hỗ
trợ" follow-up promise entirely — the guide owns the hotline instruction on
failures.

### Settings-page change (frontend)

`frontend/src/components/atomic-crm/integrations/TingtingSection.tsx`: new
"Hotline hỗ trợ" PlainField (`id="tingting_hotline"`) between the API key and
the Zalo OA block, Vietnamese hint ("Đã đặt sẵn — sửa khi cần đổi số"). The
field pre-fills with the stored value (it is not a secret); a save sends
`hotline` only when the trimmed edit differs from stored, so an untouched or
cleared field can never wipe the seed. `api.ts` types gained `hotline` on
`TingtingSettings` / `TingtingSettingsUpdate`. No registry change was needed
(the component and its file are already registered) — the STOP condition never
triggered.

### Expansion verification

Backend: `pytest` focused batch (`test_graph_runner_turn`
`test_tingting_api` `test_tingting_verify_exhaustion`
`test_graph_proactive_turn` `test_lead_extraction` `test_smoke_turn`
`test_persistence_worker`) → 342 passed, incl. the new
`test_the_hotline_round_trips_and_reads_the_plaintext_seed`; `alembic upgrade
head` applied 0058 to the dev DB (row reads `('tingting_hotline',
'+84 914 827 988', False)`), a second run is a no-op, and
`TingtingApiService.hotline()` / `admin_view()` return the seeded number;
both live smoke probes re-ran green against the seeded DB (the hotline probe
now asserts the reply built from the STORED value). Ruff clean; pyright 0
errors on all touched files. The reviewed boundary snapshot grew +2 provider
rows (`hotline`/`replace_hotline`'s `db.get` configuration reads — same shape
as their `reset_oa_id` siblings) with the file's annotation convention and a
recomputed digest. `test_migration_roundtrip_walk` +
`test_support_handoff_reply_send` + `test_extraction_intent_escalation_concurrency`
(integration lane) → 5 passed in 20:03 — every migration including 0058
survived upgrade → downgrade → upgrade. The seed lifecycle was additionally
proven directly on the dev DB: seed reads back verbatim, an admin edit
re-seals as `v1:` ciphertext AND survives a downgrade/upgrade cycle
(downgrade deletes only the exact seed value; the re-upgrade WHERE guard
skips an existing row), and the canonical seeded value was restored
afterwards.

Frontend: `vitest --project app src/components/atomic-crm/integrations` →
58 tests / 6 files passed (twice; one earlier run failed on a port collision
from a parallel session, not on assertions). `npm run typecheck` → the only
error is in `src/components/atomic-crm/projects/domain/project-brief-ingest.ts`
— the two teammates' in-flight projects lane, untouched by me.

### Expansion residual risk

- Pre-migration databases (seed not yet applied) quote the no-number sentence
  and log a per-turn warning until `alembic upgrade head` runs — visible, honest.
- Clearing the field in the admin UI is possible via API semantics
  (`replace_hotline("")`); the frontend never sends empty, so only a direct
  API call can clear it, and the bot then degrades to the no-number reply
  with the warning flag.
- A teammate's in-flight edit to `backend/app/api/projects.py` currently fails
  `test_every_http_endpoint_matches_the_reviewed_authority_snapshot`
  (projects route count 28 vs snapshot 27) — their lane; I did not touch the
  file or the snapshot.



Ruling (product owner, 2026-09-29): on the TingTing app OA nobody chats as a
human, so the bot must never escalate to a human agent/queue. Every former
escalation point instead actively encourages a call to +84 914 827 988
(candidate-facing Vietnamese, bot tone, never promising an in-chat reply).
Other OAs keep today's behavior. Implemented following the e1e5d095 pattern
(fixed code-owned replies, no queue write, wording-drift guards).

## Escalation-path map found (TingTing OA = zalo_oa + account_key "tingting")

1. `_agent_turn` support-OA routing branch (lanes.py): confident non-support
   intent → `_consultant_handoff(reason="tingting_support_handoff")` + the
   consultant-promise reply ("Vui lòng chờ chuyên viên tư vấn liên hệ.").
2. Reply-suffix escalation hook (lanes.py, tail of `_agent_turn`): any reply
   ending with the consultant sentence → queue write. Fired when the model
   echoed the dictated line (redirect budget exhausted, explicit off-scope
   topic, unconfigured API) or returned the verify-exhaustion reply.
3. Persona/API-guide copy (tingting_guide.py): four directives quoting the
   consultant sentence, plus the guide tail telling the bot to collect the
   employee's phone number "để được hỗ trợ" (human follow-up promise).
4. Identity-verification exhaustion: `TINGTING_VERIFY_EXHAUSTED_REPLY` ended
   with the consultant sentence; the verify tool also wrote `needs_human` via
   `mark_tingting_verification_exhausted` (retrieval port + repository).
5. Post-send candidate extraction (candidate_extraction.py): explicit
   human-review evidence → `escalate_extracted_intent` → HUMAN queue — wired
   for every SENT turn (chatbot_worker.py:505), so reachable on TingTing.

## What changed per path

1. Routing branch now returns `TINGTING_HOTLINE_REPLY` with no queue write;
   trace label `support_only_handoff` → `support_only_hotline`
   (schemas/bot_run.py label set updated).
2. Suffix hook deleted; `_consultant_handoff` deleted (both call sites gone);
   removed from runner imports/`__all__` together with
   `TINGTING_HANDOFF_REPLY`/`TINGTING_HANDOFF_REASON`.
3. Persona/guide quote the hotline reply in the same three+one spots; the
   guide tail now says the honest "can't run this step" + the hotline line
   instead of collecting a number; all "chuyển chuyên viên" wording is gone.
4. Exhaustion reply composes the hotline tail; the tool dictates it verbatim;
   `mark_tingting_verification_exhausted` removed from ports + repository
   impl + call site (the counter itself stays).
5. Extraction escalation skips TingTing-OA conversations (identity check
   mirrors `lanes._tingting_account_conversation`; services don't import the
   graph package, so the two-line identity read is duplicated, not shared).
   Non-TingTing escalation untouched.
6. Deploy-gate smoke probe `support-oa-handoff` → `support-oa-hotline`: now
   asserts the hotline reply DELIVERED **and** thread stays BOT, no
   needs_human, no escalation note (the reverse of the old HUMAN assertion).

## Where the hotline number lives

**Superseded by the scope expansion (see the section at the top): the number
is NOT runtime copy anymore.** The authoritative source is the
`tingting_hotline` row in `integration_settings`, seeded with +84 914 827 988
by Alembic 0058 and read at turn time; the only place the digits exist in
source is the migration's seed, pinned by
`test_the_seed_migration_pins_the_owner_approved_hotline`. Runtime replies
are built around the stored value with no fallback constant. (The original
phase's wording below described the pre-expansion design and is kept only for
the change history of that intermediate state.)

Original-phase design record: the reply was then the code constant
`TINGTING_HOTLINE_REPLY`; e1e5d095 had set the precedent of operator-approved
copy as code (18007228 still lives that way in lanes.py for the recruitment
channels — deliberately unchanged, different OA surface).

Copy (no hours/callback/email invented; no in-chat human promised):

> Dạ tình huống này em chưa hỗ trợ được qua tin nhắn ạ. Anh/chị vui lòng gọi
> ngay hotline +84 914 827 988 để chuyên viên hỗ trợ mình nhé ạ.

("chuyên viên" = on the phone, mirroring the operator-approved 18007228
wording; the sentence explicitly says nothing is supported in-chat.)

## Verification (all commands from backend/, dev DB up)

- `pytest tests/test_tingting_verify_exhaustion.py tests/test_tingting_api.py
  tests/test_lead_extraction.py -q` → 197 passed
- `pytest tests/test_graph_runner_turn.py -q` → 122 passed (rewritten:
  routing-branch test, drift guard pinning BOTH numbers, model-echo test →
  zero escalations, exhaustion-dictation test → zero escalations)
- `pytest tests/test_smoke_turn.py tests/test_smoke_turn_progressive.py
  tests/test_persistence_worker.py tests/test_runtime_surface_inventory.py -q`
  → 26 passed
- `pytest tests/test_architecture_boundaries.py
  tests/test_deployment_makefile.py -q` → 61 passed
- Integration (local Postgres): `tests/integration/test_support_handoff_reply_send.py`
  → 1 passed (file pruned to the still-real post-send escalation contract);
  `tests/integration/test_extraction_intent_escalation_concurrency.py` →
  2 passed (non-TingTing escalation intact)
- Live probe: `scripts/smoke_turn._run_support_oa_hotline_smoke` +
  clarify probe against the dev DB → both `SMOKE OK … outcome='sent'`
- `ruff check .` → clean (fixed one F401 `uuid` in
  app/services/retrieval/repository.py left by the deletion)
- `uvx pyright app/graph` → 0 errors; `uvx pyright
  app/services/candidate_extraction.py app/schemas/bot_run.py
  app/services/retrieval/repository.py scripts/smoke_turn.py` → 0 errors
- New test: `test_persist_never_escalates_a_tingting_oa_conversation`
  (test_lead_extraction.py) pins the extraction gate; the drift guard pins
  `914827988` and `18007228` so neither channel can inherit the other's copy,
  and `test_small_talk_gets_a_redirect_budget_before_any_handoff` pins that
  the consultant promise ("chuyên viên tư vấn liên hệ") can never return to
  the persona/guide.

Full backend suite NOT run (40+ min, controller's call). Scope: 14 backend
files, all under app/graph, app/services, app/schemas, scripts, tests. No
frontend, docs, or AGENTS.md touched; nothing staged or committed.

## Residual risk

- `preserve_turn_ownership` on `escalate_extracted_intent` now has no
  production caller (the deleted handoff was its only user). The state-layer
  parameter stays as generic machinery; the two DB tests that pinned it were
  removed with their trigger. Safe, but a future in-lane escalation must
  re-learn the suppression lesson (its docstring history lives in git).
- The decision-trace label rename (`support_only_handoff` →
  `support_only_hotline`) changes trace payloads; nothing in-repo consumed
  the old value outside the schema, but external dashboards keying on it
  would see the new label.
- Verify-exhausted employees now get the hotline instead of a consultant
  callback — that is the ruling, but it is a visible support-experience
  change worth mentioning to the operator.
- The extraction gate skips escalation but, like the evidence-less path,
  also skips lead persistence for that turn on TingTing threads (employees
  there are not recruiting leads; matches the branch's prior shape).
- `backend/app/graph/context.py:143` still has the recruitment prompt asking
  for SĐT "để chuyên viên tư vấn liên hệ lại" — recruitment-OA behavior,
  intentionally untouched per the ruling's scoping.
