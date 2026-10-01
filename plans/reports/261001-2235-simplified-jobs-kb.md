# Simplify Jobs KB metadata

User requested removal of `vacancies: null` and `employment_type: null`. Both fields are retired entirely from the Project KB contract, including populated legacy values. This work preserves the earlier authorized production/UI/recruitment audit and KB export changes. All changes remain unstaged and uncommitted on main at `35d970689cbb092e4f9100f1e60305c9bd7505ed`.

## Cause and implementation

The backend JobItem model and frontend Markdown schema declared both optional fields, so generated records and exports carried null placeholders. Merely hiding nulls would leave the fields in training/schema contracts and allow old populated values back into output. Removed the declarations, Jobs questionnaire fields, frontend defaults/serialization and legacy backfill assignment. All other category document schemas are unchanged; the Jobs schema changes only by removal of these two properties.

The existing pure legacy boundary transformer now drops four retired structural keys: `job_ids`, `jobs_ids`, `vacancies`, and `employment_type`. Markdown, complete/embedded JSON, direct pages, stored chunk/digest/search outputs, cached bot evidence and export paths share this transformation. Old inputs remain accepted. Historical source, payload, checksums, embeddings and cutover/rollback checkpoints are not rewritten. Ordinary prose, code examples, comments and quoted/bullet YAML note blocks survive, including escaped keys and standard indentation/chomping markers. Retired-only input cannot produce a fake nonempty KB or download.

Jobs projection no longer invents a headcount of 1. It preserves existing Job capacity values and leaves new derived roles unknown. Generic Job API/database fields and hand-written migrations remain intact. Review identified and fixed two adjacent output/count issues: admin active-role counts now include unknown capacity while excluding explicit zero, closed roles and stale Jobs revisions; revision retry receipts clean their historical normalized payload without mutating saved identity.

## Verification

- Final focused boundary/API-output/direct-context/compatibility/architecture suite: **239 passed**, including 60 combinations of ordinary note block keys, indicators and bullets.
- Backend owner-focused parser/contracts/projections/training/base-service/architecture: **148 passed**; PostgreSQL capacity/authority cases: **2 passed**.
- Backend unit regression: **3288 passed, 37 optional checks skipped**, on the final frozen source, including the final note-key compatibility repair.
- Full isolated PostgreSQL 16+pgvector suite: **295 passed**. Each lane migrated its uniquely owned loopback database to current Alembic head and dropped it afterward.
- Frontend full app suite: **896 passed across 118 files**; affected frontend suite: **168 passed**.
- Real desktop/mobile browser export and complete-template checks: **4 passed**, including 390/900/1440px widths, saved legacy uploads containing all four retired fields, draft preservation and empty-KB failures.
- Backend full Ruff and expanded affected-module Pyright: **pass; 0 errors/0 warnings**. Frontend app+Node types pass; ESLint **0 errors/35 existing warnings**. Registry (232 paths), production build, built-browser smoke and doc routing (32 paths, 4 targets, 4 documents) pass. Dependency lock is unchanged.
- Independent review found no outstanding issue in this scoped change. Root reviewed the incremental production diff and verified no new TODO/FIXME/HACK markers.

Evidence logs: `/tmp/vfic-simplified-kb-{boundaries,backend-all,pg-all,frontend-all,e2e,backend-lint,backend-types,frontend-types,frontend-node-types,frontend-lint,registry,build,smoke,doc-links}.log`; owner logs `/tmp/vfic-retired-kb-job-metadata-unit-final.log`, `/tmp/vfic-retired-kb-job-metadata-counts-pg.log`, and `/tmp/vfic-project-kb-remove-role-metadata-frontend-tests.log`.

## Portable artifacts

`plans/exports/2026-10-01-simplified-jobs-kb.patch` is the full cumulative binary/full-index diff against main at 35d970689. `plans/exports/2026-10-01-simplified-jobs-kb-incremental.patch` applies after the preserved full `2026-10-01-project-scoped-kb.patch` (SHA256 `0be9ad39620b76c36a7919ca8f5ec7d6f95ee86d83d045112ba96547f02e36ce`). Use one option. Both are checked/applied in fresh trees, compared for all file bytes and executable modes, and reverse-checked; HEAD, real index, worktree status and previous artifact hashes remain unchanged. External manifests/README carry exact final sizes, paths, SHA256 and validation results.

## Boundaries

No deployment, commit, branch, push, PR, merge, schema migration, dependency update or history rewrite. Verification used task-owned PostgreSQL/Redis containers only; unrelated existing containers were preserved. The 37 existing optional checks require external provider credentials, captured corpus or unavailable pinned edge-test images/binaries. Local tests do not prove production or live-provider behavior. Safari/Firefox were not exercised.
