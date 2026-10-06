# Agent Completion Report — Reliable lead-details extraction (P0 + P1)

## Task record

- Task: "how to have a reliable lead details extraction workflow? currently we
  still don't fill in properly even after candidate provide" → approved plan
  **P0 (deterministic-first capture) + P1 (a queue that cannot fail silently)**.
- Scope: inbound deterministic capture for closed-shape fields, one unified
  write with the existing name capture, bounded retry + visible failure for the
  deferred LLM job, loud enqueue failure. Out of scope (next stages): P2
  observability counters + gap sweep, P3 prompt/normalizer recall work
  (`desired_job`, address), P4 recruiter UI feedback.
- Files changed (mine, 15): `services/lead/normalizers.py`
  (`deterministic_lead_details`), `services/candidate_extraction.py`
  (`persist_explicit_name` → `persist_explicit_details`, one upsert),
  `services/webhook.py` (call site), `conversation_messaging/infrastructure/ingress.py`
  (Messenger call + logger), `workers/persistence_worker.py` (Retry×3, re-raise),
  `workers/chatbot_worker.py` (enqueue-failure ERROR), tests: new
  `test_deterministic_lead_details.py`, new `test_inbound_deterministic_details.py`,
  new `test_chatbot_persist_enqueue.py`, + renames/extension in
  `test_persistence_worker.py`, `test_lead_extraction.py`,
  `test_recruitment_intake.py`, `test_webhooks.py`,
  `test_conversation_service_composition.py`; docs: `system-architecture.md`
  §2.6, `codebase-summary.md` row.
- Instructions retrieved: `AGENTS.md`; `docs/development/code-standards.md`;
  `docs/development/testing.md`; `docs/architecture/system-architecture.md`.
  Production evidence gathered before designing: worker logs on `bot.tingting.vip`
  (jobs run 7–13 s, `Job OK`, no failure markers in the post-deploy window) and
  read-only SQL over `leads`/`messages` (212 contacts stated a phone → 205 leads
  have one; 13 stated a name → 4 null; 55 stated an age → 17 null; salary filled
  on 8/1209).
- Approval required: commit / push / deploy (not requested for this task).
- Approval evidence: N/A — verified locally, awaiting the user's word.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Tier 1 lands on the inbound path: `persist_explicit_details` writes name + age + birth year + expected salary in **one** upsert for Zalo (`services/webhook.py`) and Messenger (`infrastructure/ingress.py`), before any queue/model/gate. Tier 2 (LLM job) can no longer fail invisibly: failures re-raise → RQ `Retry(max=3, interval=[15,60,300])`, landed failures sit in the failed-job registry; an enqueue failure logs ERROR with the chat id. |
| Diff is limited to the approved scope | PASS | `git status --short` → 15 paths, all listed above; the previously uncommitted attribution/interest work is now on `main` (commits `312d1920`, `ab7fd11e`, `ab161c2c`) and untouched by me. |
| Protected operations were avoided or approved | PASS | No commit, push, branch, PR, or deploy performed for this task. No migration (the `0070` head belongs to a separate committed change). |
| Focused tests/checks pass | PASS | New pins: `test_deterministic_lead_details.py` → **6 passed** (captures AND non-captures: no keyword ⇒ no salary, noise ⇒ no age, age bound stays in `normalize_lead`); `test_inbound_deterministic_details.py` (real PostgreSQL) → **4 passed** (Messenger name+age+salary before any queue; numeric-only; nothing written for a plain question; Zalo merge into the trigger stub, exactly one row); `test_chatbot_persist_enqueue.py` → **2 passed**; `test_persistence_worker.py` retry + re-raise pins → pass. Renamed call sites: `test_webhooks.py` + `test_conversation_service_composition.py` → **51 passed** together; `test_lead_extraction`/`intake`/`deterministic`/`composition` → **242 passed**. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -m "not integration"` → **3701 passed, 28 skipped, 0 failed** (11m16s); touched integration files → **26 passed** (3m03s). An earlier parallel attempt showed alembic-setup timeouts purely from two suites running at once; the sequential rerun above is the result of record. |
| Lint passes for affected code | PASS | `ruff check .` → "All checks passed!" (run after every batch). |
| Type checking passes for affected code | PASS/N-A | The release gate's type scope is `app/graph`, which this task does not touch (`pyright app/graph` → 0 errors on the current tree). The changed files are untyped service/worker modules with no type gate configured. |
| Build/import validation passes for affected code | PASS | The integration lanes migrate a disposable PostgreSQL to the current head (`0070_backfill_lead_age_from_birth_year`) and exercise every changed module end to end. |
| Security and privacy impact reviewed | PASS | Regexes run on message text only — no SQL is built from candidate input; failure logs carry the exception type and chat id, never message content or PII (repo logging rule). No new endpoints, no new secrets, no new tables. |
| Performance and async-I/O impact reviewed | PASS | Tier 1 is in-memory pattern matching plus the lead upsert that already existed — a message with no details performs **zero** extra writes (pinned by `test_a_message_without_any_detail_writes_nothing`). No extra query on the inbound path. Retry only runs on failure (3 attempts, backoff 15 s/60 s/300 s). |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | Inbound detail write is best-effort (rollback + ERROR log, the message row above survives — same contract as the old name capture); the LLM job's authority-suppression early return is preserved (existing test); enqueue returns bool on both paths. Behavior superset: `persist_explicit_details` writes everything `persist_explicit_name` did and adds the deterministic fields; both call sites migrated (grep: 0 old references in `backend/`). |
| Documentation impact handled | PASS | `system-architecture.md` §2.6 (two tiers, why the split, retry contract), `codebase-summary.md` module row. `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets … resolve". |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff -- backend docs \| grep -cE '^\+.*(TODO\|FIXME\|HACK)'` → 0. |
| Final `git diff --check` passes | PASS | `git diff --check -- backend docs` → exit 0. |
| Final `git status --short` reviewed | PASS | 15 paths — all mine, listed in the task record; no foreign edits in the set. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - **P2 (next):** per-drop-reason counters (`greeting_gate` / `mode` /
    `human_review` / `llm_error` / `authority`) on `/metrics`, plus a daily
    gap sweep (re-enqueue extraction for messages that state a detail the lead
    lacks) — `scripts/backfill_messenger_candidates.py` already proves the
    pattern. The production gaps (17/55 ages, 4/13 names) are what it targets.
  - **P3:** recall work on the open fields — salary landed on 8/1209 leads
    because the LLM rarely emits `expected_salary`; the deterministic tier now
    covers the common shapes, but keyword-free statements still need the model.
  - A single-letter final name token (`"Nguyễn Văn A"`) is dropped by
    `extract_self_reported_name` — pre-existing rule, surfaced while writing
    the integration fixture; worth a deliberate decision (it is what protects
    against capturing `"A"` from prose).
  - Two concurrent pytest sessions collide on the integration DB's alembic
    setup (120 s subprocess cap) — run heavy suites sequentially, as done here.
  - Not committed/deployed; `main` already carries the earlier attribution and
    interest tasks.
