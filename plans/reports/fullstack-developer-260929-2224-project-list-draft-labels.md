# Project list draft labels — completion report

Date: 2026-09-29 (Asia/Singapore)
Owner: v058-list-labels (fullstack-developer subagent)
Scope: state-driven draft labels in the project list, per the agreed feature spec.

## Data-source decision

**Adopted the authorized minimal fallback: every inactive project renders
"Bản nháp".**

Evidence scouted:

- `backend/app/schemas/projects.py` — `ProjectOut` (the list payload) carries
  `is_active`, `knowledge_mode`, `index_card`, `discovery_revision`,
  `knowledge_document_count`, `feature_readiness`. **No ingest/status field.**
- `backend/app/api/projects.py` — ingest/category state is exposed only at
  `GET /projects/{project_id}/categories` (strictly per-project). The list
  endpoint has no status data.
- `frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts`
  — the catalog hook is per-`projectId` and owns a mutation + revision poll
  loop; it is not reusable for a list. Calling the underlying service per
  inactive project would be N fan-out requests.

The four-state design (Bản nháp / Đang nạp / Sẵn sàng / Lỗi nạp) therefore
cannot be truthfully rendered from list-level data. Per the governing
no-fabrication rule and the task's explicit fallback authorization, inactive
projects show "Bản nháp" derived from `is_active` only. No optimistic "Sẵn
sàng", no inference from `knowledge_document_count`, timestamps, or revision
counters.

**Tradeoff recorded:** draft ingest progress is invisible at list level until
a batch status field lands on `ProjectOut` (or a list-level status endpoint)
on the backend. When that exists, the label mapping in `ProjectList.tsx` is
the single place to extend.

## Changes

- `frontend/src/components/atomic-crm/projects/ProjectList.tsx` — the state
  badge now renders `Đang hoạt động` / `Bản nháp` (was `Đang hoạt động` /
  `Tắt`). Badge styling untouched; toggle semantics untouched; a short
  comment records the fallback rationale. No new imports; existing
  `domain/project-knowledge-policy` imports left exactly as found.
- `frontend/src/components/atomic-crm/projects/ProjectList.test.tsx` — added
  one test: active project shows "Đang hoạt động", inactive shows "Bản nháp",
  and the old "Tắt" label is gone. All 5 pre-existing tests kept unchanged
  and passing.

## Verification

| Command (from `frontend/`) | Result |
| --- | --- |
| `npx vitest run --config vitest.config.ts --project app src/components/atomic-crm/projects/ProjectList.test.tsx` | 1 file, 6/6 tests passed (17.9s) |
| `npm run typecheck` | 5 errors, **all in `ProjectCreate.test.tsx`** (teammate's in-flight file, on my do-not-modify list); zero errors in any file I touched. Confirmed by filtering the full error list. |
| `grep` for other tests asserting the old "Tắt" badge | none — no test outside `ProjectList.test.tsx` references it |

Git state: only `ProjectList.tsx` and `ProjectList.test.tsx` modified by me,
unstaged, nothing committed or staged (per instructions). `frontend/registry.json`
untouched.

## Unresolved questions

- Backend follow-up (out of my scope): expose ingest state on `ProjectOut`
  or a list-level endpoint so Đang nạp / Sẵn sàng / Lỗi nạp can be rendered
  honestly.
- The teammate's `ProjectCreate.test.tsx` currently fails typecheck (5
  errors); expected to be resolved on their side before commit.
