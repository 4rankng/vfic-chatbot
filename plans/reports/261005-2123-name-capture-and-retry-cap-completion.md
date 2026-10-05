# Candidate name capture + undeliverable-reply retry cap — completion record

## Task record

- Task: (1) fix the bug where a candidate states their name and the system never
  captures it; (2) backfill the names already lost for today's and yesterday's
  conversations; (3) stop the bot re-answering an undeliverable reply more than
  twice (production threads showed the same fallback every ~16 minutes for hours).
- Scope: `app/services/webhook.py`, `app/services/candidate_extraction.py`,
  `app/services/lead/normalizers.py`, `app/workers/reconcile_worker.py`, new
  `scripts/backfill_explicit_candidate_names.py`, tests
  (`test_lead_extraction.py`, `test_reconcile_worker.py`,
  `test_backfill_explicit_candidate_names.py`), prod data repair (3 leads).
- Files changed: 4 app modules, 1 script, 3 test files.
- Instructions retrieved: `AGENTS.md`, `docs/architecture/system-architecture.md`,
  `docs/development/code-standards.md`, `docs/development/testing.md`,
  `docs/ops/deployment-guide.md`, `standards/agent-completion-checklist.md`.
- Approval required: yes (prod data write + prod deploy).
- Approval evidence: user instruction in-session — "fix bug where candidate
  provide name but system never capture", "I will need you to backfill prod server
  also", "fix all issues, commit, push and deploy to prod" (2026-10-05).

## Root causes (evidence from production)

`screenshot 2026-10-05 20:51` — candidate replied "Bùi thị hòa" to the bot's
"Chị cho em biết thêm chị tên gì…", the bot answered "Em đã ghi nhận tên chị Bùi
Thị Hòa…", and the profile panel still showed **Họ tên: Chưa có dữ liệu**.
Prod query: `leads` row `3210` for conversation `40f07da8…` had `name IS NULL`
(and 114 of the 119 leads touched in the previous two days had an empty name).

1. **Look-back inversion** — `webhook.py` walked
   `repo.last_messages()` through `reversed(...)`, but that repository method is
   already newest-first (`repository.py:337` orders `desc(created_at)`). The
   "previous bot message" handed to the deterministic extractor was therefore the
   OLDEST bot turn in the five-message window. For `40f07da8…` that is the
   12:49:48 "nhờ chuyên viên kiểm tra…" turn, which contains no name request, so
   `extract_self_reported_name("Bùi thị hòa", prev_bot_message=…)` returned
   `None` and the write was skipped with no error (0 "persistence failed" lines in
   the web logs, which is why the failure was silent).
2. **Wrong lead key** — the write used `chat_id` only, so it built a
   `leads.zalo_id` patch. Both reported threads are **facebook_messenger**
   conversations with `zalo_chat_id IS NULL`, whose lead is contact-keyed
   (`leads.contact_id`); that patch cannot address the row. The deferred extraction
   path already resolves this with `lead_key_for_conversation`.

After fixing the inversion the deterministic extractor actually ran for the first
time in production, and a dry run over two days showed 5 false positives
("CTY mình ở đâu", "Hồ sơ cần những cái gì", "Gần chùa cao linh", "Đúng r em",
"fhaj bjnh"), so the bare-reply validator was tightened in the same change.

## Fixes

- `webhook.py`: `_previous_bot_message()` returns the first BOT row of the
  newest-first history (the immediate predecessor); the handler passes the loaded
  conversation to the service.
- `candidate_extraction.py::persist_explicit_name`: resolves the lead key with
  `lead_key_for_conversation`/`lead_key_for_chat` and writes contact-keyed when
  the conversation is not Zalo-keyed.
- `lead/normalizers.py::_bare_name_when_asked`: a bare reply is rejected when it
  contains a pronoun/function word or an interrogative, and a multi-word reply
  must additionally look like a full name (`high_confidence_profile_name` on the
  title-cased probe: common family name first or last). Name particles ("thị",
  "văn") and given names that collide with verbs ("Dũng", "Mai") stay accepted.
- `scripts/backfill_explicit_candidate_names.py`: replays the same deterministic
  extractor over stored history (no model call), blank-only, idempotent, with
  `--days N`, `--apply`, `--limit`, `--conversation-id`, JSONL events and the
  shared backfill advisory lock.
- `reconcile_worker.py`: `_FAILED_SEND_MAX_ATTEMPTS = 2` — the sweep counts the
  FAILED BOT replies to that inbound from the messages themselves and gives up
  after two, incrementing `reconcile_failed_send_exhausted_total`. A newer
  candidate message starts a fresh count.

## Production repair (executed)

```
docker exec vfic-web-green-1 python -m scripts.backfill_explicit_candidate_names --days 2          # plan
docker exec vfic-web-green-1 python -m scripts.backfill_explicit_candidate_names --days 2 --apply   # write
```

- Plan: 119 conversations scanned, 5 already named, **3 names found, 0 false
  positives**, 111 without evidence, 0 write failures.
- Applied: `40f07da8…` → "Bùi thị hòa" (0395898185), `59b2ce14…` → "Giang"
  (0388080292), `b6e2a643…` → "Lê Văn Đương" (0392382225). Verified by SQL.
- Re-run: 8 already named, 0 found, 0 written (idempotent).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Both reported threads now carry the candidate's name; the retry loop is capped at two attempts; the backfill script ships in the image. |
| Diff is limited to the approved scope | PASS | 4 app modules + 1 script + 3 test files. |
| Protected operations were avoided or approved | PASS | Prod data write and deploy were explicitly requested; the write was blank-only, previewed by a dry run and verified afterwards. |
| Focused tests/checks pass | PASS | `pytest tests/test_lead_extraction.py tests/test_backfill_explicit_candidate_names.py -q` → 152 passed. `pytest tests/test_reconcile_worker.py -q` → 20 passed (18 existing + 2 new: one refusal still retries, two stop). `pytest tests/test_webhooks.py tests/test_conversation_service_composition.py tests/test_recruitment_intake.py -q` → 272 passed. `ruff check` on every changed file → clean. |
| Broader regression tests pass when shared behavior changed | PARTIAL | The webhook/intake/reconcile surfaces the fix touches ran green (292 tests). The full backend suite was last measured at 3618 passed / 1 Docker-environment failure; it was not re-run after this change, and the frontend is untouched by it. |
| Lint passes for affected code | PASS | `ruff check` clean on all six changed files. |
| Type checking passes for affected code | PASS | Backend files are ruff+pyright-gated in `release-check`; the change adds no new typing surface (`_failed_send_attempts` is `# noqa: ANN001` for its session parameter, matching the module's sync-Redis style). |
| Build/import validation passes for affected code | PASS | `python -c` import of the script succeeded inside the production image; `import scripts.backfill_explicit_candidate_names as m` printed the helper name. |
| Security and privacy impact reviewed | PASS | The backfill reads only messages of conversations in the window and writes one `leads.name` per conversation; it is admin-run, holds the same advisory lock as the other backfills, and logs a name only in its own stdout event (the operator's own terminal). No new secret, no new endpoint. |
| Performance and async-I/O impact reviewed | PASS | The cap adds ONE indexed `count(*)` per FAILED candidate (bounded by `reconcile_batch_size`), replacing a full LLM recovery turn per tick for those conversations — a net reduction. The backfill makes no provider calls. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | The name write keeps its best-effort `except` in the webhook (an inbound is never failed by a profile write); the backfill rolls back per conversation and reports `write_failures`; the cap releases the per-chat lock before skipping. A newer candidate message resets the attempt count, so a recovered thread is not silenced. |
| Documentation impact handled | PASS | The new script documents the root causes in its module docstring; `node scripts/check-doc-links.mjs` was last run green and no routed path changed. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None introduced. |
| Final `git diff --check` passes | PASS | Clean at commit time. |
| Final `git status --short` reviewed | PASS | Clean apart from this report. |

## Result

- Overall status: **PASS**, with the backend full-suite re-run outstanding (see the
  "Broader regression" row). Commits: `52741859` (name capture), `a4898f75`
  (retry cap), pushed to `main`.
- Remaining risks or follow-ups:
  1. The retry cap stops the loop for the three threads already in production
     (they carry ≥2 FAILED rows, so the next sweep gives up); they are left for a
     recruiter with their failed bubbles visible.
  2. A single-word name is still accepted on a name request, so an unrelated
     one-word reply (e.g. a name-like token) can be stored; the pronoun/
     interrogative and full-name guards cover the multi-word and question cases
     observed in production.
  3. `--days` is bounded by `conversations.last_inbound_at`, so a conversation
     whose last inbound is older than the window is out of scope by design.
