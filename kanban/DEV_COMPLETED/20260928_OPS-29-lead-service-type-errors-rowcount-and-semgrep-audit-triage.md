---
id: OPS-29
title: "backend/app/services/lead carries live type-check errors: Result.rowcount attribute misuse (repository.py:226,251), ViewerIdentity argument errors (service.py:58,453), assignment narrowing (normalizers.py:292); Semgrep avoid-sqlalchemy-text audits at repository.py:93,124 triaged false-positive"
severity: low
area: backend
labels: [type-safety, sqlalchemy, static-analysis, lead-service]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-28
---

# OPS-29 — backend/app/services/lead carries live type-check errors; Semgrep text() audits triaged false-positive

**Severity:** low · **Area:** backend · **Labels:** type-safety, sqlalchemy, static-analysis, lead-service

**Trạng thái:** DEV_COMPLETED — 2026-09-28: four of the five diagnostics were already fixed at HEAD by `0e6c0747`/`8f49f29d`; the two Semgrep audit sites silenced with the verified short-form `# nosemgrep: avoid-sqlalchemy-text` (the long-form id is inert — the registry doubles the rule id). pyright → 0 errors, 227 lead tests green.

## Problem

`backend/app/services/lead/` (the lead persistence slice, a known bug-magnet area)
currently fails static analysis on every full scan:

| Location | Diagnostic | Reality |
| --- | --- | --- |
| `repository.py:226` | Pyright `reportAttributeAccessIssue`: `Result[Any]` has no attribute `rowcount` | Works at runtime (`CursorResult` has `rowcount`) but the type contract is wrong; a future refactor to another execute path breaks silently |
| `repository.py:251` | same as above | same |
| `service.py:58` | Pyright `reportArgumentType`: `User` not assignable to `ViewerIdentity` (`id`/`role` invariance, `Mapped[UUID]` vs `UUID`) | Passes a full ORM model where the protocol expects plain values |
| `service.py:453` | Pyright `reportArgumentType`: `InstrumentedAttribute[UUID | None]` passed as `ColumnElement` to `viewer_scope_condition` | Same class: ORM attribute vs column expression |
| `normalizers.py:292` | Pyright `reportAssignmentType`: `str | None` assigned to `str` | Missing None guard |
| `repository.py:93,124` | Semgrep `python.sqlalchemy.security.audit.avoid-sqlalchemy-text` | **False positive** — see Evidence |
| `service.py:128,163`, `normalizers.py:91` | ast-grep warning: unchecked `int()`/`float()` parse | Minor; inputs are internal |
| `normalizers.py:118-376` | typos: `toi`/`cach`/`bui`/`thay` | False positives — Vietnamese words without diacritics |

## Evidence

- Re-run 2026-09-28 with a full LSP probe over `backend/app/services/lead/`:
  20 diagnostics, errors in `repository.py`, `service.py`, `normalizers.py`.
- Injection triage of the two Semgrep audit sites: both SQL constants use **bound
  parameters** (`:zalo_id`, `:contact_id`, …). The only string interpolation is
  `_merge_assignments(source)` (repository.py:26), which embeds the literal column
  prefixes `"EXCLUDED."` or `":"` into static SQL constants — no runtime/user input
  reaches the SQL string. The `avoid-sqlalchemy-text` rule flags all `text()` usage
  and does not trace taint here, so these two are audit noise, not vulnerabilities.
- These findings were first raised as a historical automated finding; the 2026-09-28
  re-run confirms they are still live at HEAD (rowcount hits at the same lines 226/251).

## Impact

- Real Pyright errors in a bug-magnet module mean `make`-level type gating cannot be
  trusted for this slice; new regressions hide among known failures.
- `rowcount` on `Result` is only accidentally correct; switching the call to
  `session.execute(select(...))` in a different session mode would raise at runtime.
- The false-positive audits desensitize readers to Semgrep output in this file.

## Suggested fix

1. `repository.py:226,251`: execute via `CursorResult` (or `cast`/`isinstance` narrow)
   so `rowcount` is typed — prefer re-exporting the execute result as
   `CursorResult` from `sqlalchemy.engine` and annotating, not `getattr`.
2. `service.py:58`: pass `ViewerIdentity(id=user.id, role=user.role)` (plain values)
   instead of the ORM `User`; `service.py:453`: pass the column object
   (`Lead.contact_id` column expression / `Lead.__table__.c.contact_id`) rather than
   the `InstrumentedAttribute` if the signature demands `ColumnElement`.
3. `normalizers.py:292`: add the None guard or narrow before assignment.
4. Leave the two Semgrep audit sites as-is but silence them with a targeted
   `# nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text` plus a
   one-line comment that all values are bound parameters — so the audit lane stops
   crying wolf on this file.
5. Skip the Vietnamese typos informationals; they are language false positives
   (worth raising upstream as an ignore rule for Vietnamese romanized words).

## Notes

- Found by an automated pi-lens finding requiring re-confirmation; confirmed live on
  2026-09-28, card opened instead of an unrequested code change to an unrelated slice.
- `backend/app/services/lead/` is in the "files that need care" set — keep the fix
  narrow and run the lead repository tests
  (`backend/tests/test_lead_repository_contact_upsert.py`,
  `backend/tests/test_lead_repository_contact_filter.py` family) after the change.

---

_Opened 2026-09-28 from the automated diagnostics re-run pass. All line references verified on the live tree._
