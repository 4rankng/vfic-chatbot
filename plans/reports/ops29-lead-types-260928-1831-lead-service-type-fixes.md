# OPS-29 — Lead Service Type Errors, rowcount, and Semgrep Audit Triage

## Outcome

OPS-29 is resolved. Four of the card's five Pyright diagnostics were already fixed
at HEAD by earlier commits (`0e6c0747` made `Viewer = User | ViewerIdentity` and
widened `viewer_scope_condition` to accept `ColumnLike` — `ColumnElement[Any] |
InstrumentedAttribute[Any]` — and `8f49f29d` widened `normalize_lead`'s
`chat_id` annotation to `str | None`); I re-verified each against the live tree
with pyright (0 errors) instead of re-fixing them. The one live gap was the
Semgrep triage: I added targeted `# nosemgrep` annotations plus bound-parameter
comments to the two f-string `text()` constants in `repository.py`, and verified
empirically that the rule now reports 0 findings across all 9 lead-slice files.

One deviation from the task text, backed by empirical evidence: the prescribed
long-form annotation `# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text`
does **not** suppress this rule. When the rule is fetched from the registry
(`semgrep --config r/python.sqlalchemy.security.audit.avoid-sqlalchemy-text`),
the loaded rule id is `python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text`
(doubled suffix), so the long form never matches. The short suffix form
`# nosemgrep: avoid-sqlalchemy-text` matches in both loading modes (suffix
match) and is what I used. Bare `# nosemgrep` also works but suppresses all
rules on the line, so I kept the targeted short form.

## Per-diagnostic disposition

| Card diagnostic | Live state found | Action |
| --- | --- | --- |
| `repository.py:226,251` — `Result[Any]` has no `rowcount` | Already fixed at HEAD by `0e6c0747`: `CursorResult` imported from `sqlalchemy.engine`, both sites use `cast(CursorResult[Any], result).rowcount` (now lines 231/256) | Verified, no change. The task preferred real typing over cast, but real typing is not reachable without a runtime change: `AsyncSession.execute()` is typed to return `Result[Any]` and `CursorResult` is its subclass, so even an annotated variable would need the same cast. The existing cast is the minimal zero-runtime-change form. |
| `service.py:58` — `User` not assignable to `ViewerIdentity` | Already fixed at HEAD by `0e6c0747`: `Viewer = User \| ViewerIdentity` union in `viewer_scope.py:55`, so the ORM `User` satisfies the union arm directly | Verified, no change needed |
| `service.py:453` — `InstrumentedAttribute` passed as `ColumnElement` | Already fixed at HEAD by `0e6c0747`: `viewer_scope_condition` now takes `ColumnLike` (`viewer_scope.py:34`), which accepts the `InstrumentedAttribute` | Verified, no change needed |
| `normalizers.py:292` — `str \| None` assigned to `str` | Already fixed at HEAD by `8f49f29d`: `normalize_lead(raw, chat_id: str \| None)` matches `_pick`'s `str \| None` return | Verified, no change needed |
| `repository.py:93,124` — Semgrep `avoid-sqlalchemy-text` audits | Live at drifted lines 95/126 (`_UPSQL`, `_UPDATE_BY_CONTACT_SQL` — the only two f-string `text()` sites; the rule does not flag the plain-string `text()` calls) | Fixed: 2-line bound-parameter comment + targeted `# nosemgrep: avoid-sqlalchemy-text` above each constant; SQL left as-is |
| ast-grep int()/float() warnings, Vietnamese typos | Out of scope per card and task | Skipped |

## Files modified

- `backend/app/services/lead/repository.py` — +6 lines (comment + `nosemgrep`
  annotation above each of the two f-string `text()` constants). No runtime
  behavior change; the SQL, and every other file in the slice, untouched.

## Verification evidence

- Pyright (backend venv, so sqlalchemy resolves):
  `cd backend && uvx pyright --pythonpath .venv/bin/python app/services/lead`
  → `0 errors, 0 warnings, 0 informations`
  (Note: plain `uvx pyright app/services/lead` without `--pythonpath` reports 5
  false `reportMissingImports` errors because pyright can't see the venv — that
  is an invocation artifact, not a code finding.)
- Ruff: `cd backend && .venv/bin/ruff check app/services/lead` → `All checks passed!`
  (`ruff format --check` flags pre-existing drift in `normalizers.py`/`service.py`
  — both untouched by me, present at HEAD; `repository.py` stays format-clean.)
- Semgrep (registry rule, fetched via uvx semgrep):
  `uvx semgrep scan --config r/python.sqlalchemy.security.audit.avoid-sqlalchemy-text app/services/lead`
  → `Ran 1 rule on 9 files: 0 findings.` (before my change: 2 findings at the
  two f-string sites)
- Focused tests (`test_lead_repository_contact_filter.py` named in the task does
  not exist; I ran every lead-related file that does):
  `pytest tests/test_lead_repository_contact_upsert.py tests/test_lead_viewer_scope.py tests/test_lead_chatops.py tests/test_lead_extraction.py tests/test_lead_gender_guard.py tests/test_lead_update_concurrency.py tests/test_recruitment_lead_domain.py -p no:randomly`
  → `230 passed in 12.37s`

## Unresolved questions / notes for the lead

- None blocking. Two working-tree observations that are **not mine** and outside
  my ownership, left untouched for you to reconcile: `Makefile` (+4),
  `docs/ops/deployment-guide.md` (+18), and the OPS-31 kanban card moved from
  TODO to QA_TESTED (untracked). My only change is `backend/app/services/lead/repository.py`.
- The kanban card's line references (226/251, 93/124) have drifted by +2/+2;
  the diagnostics themselves map cleanly to the current tree as described above.
- If another card prescribes long-form `nosemgrep` ids for registry rules, use
  the short suffix form — the long form silently fails to suppress.

Docs impact: none — comments and static-analysis annotations only; no
user-visible behavior, command, contract, or architecture change.
