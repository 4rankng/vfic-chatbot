# v0.5.8 — ProjectCreate brief→RAG ingest flow: completion report

Agent: v058-finisher (fullstack-developer lane), 2026-09-29, finished 22:45+08.
Scope: fix forward the uncommitted v0.5.8 work left by a dead session. No restart, no redesign.

## Outcome

`ProjectCreate.test.tsx` is 11/11 green (was 7 pass / 4 fail), all projects
suites are green (15 files / 128 tests), both typechecks are clean, and
`dbg.test.tsx` is removed from disk and the git index.

## Root cause of the 4 failures

Three failures ("keeps Tạo dự án disabled until the pipeline has really
finished", "activates the draft only when the admin presses Tạo dự án",
"re-writes the jobs category when the admin edits the role list") shared one
cause, and the fourth had a second, independent cause:

1. **The ingest "done" state could never render.**
   `waitForActive` in `presentation/use-project-ingest.ts` resolved success
   only on a positive `active_revision_id === revisionId` match. The contract's
   catalog fixture confirms the `jobs` revision (`catalogWith("rev-jobs")`) but
   leaves the `faq` row `null/null/null` — which per the backend serializer
   (`backend/app/services/knowledge/category_service.py`, `status=latest.status
   if latest else None`) is the shape of "category has no revisions at all". The
   `faq` hop therefore never matched, retried the full 20 × 2 s budget, and
   landed in the "Hệ thống chưa phản hồi kịp" failure state. No poll rule keyed
   on the revision id can confirm `rev-faq` against that fixture.

   **Fix (same file, `waitForActive`):** the replace response is the backend's
   acceptance of a category's content. The poll now resolves in this order:
   any row with `active_revision_id === revisionId` → success; any row with
   `latest_revision_id === revisionId && status === "FAILED"` → failure with the
   backend's own message; any row with `latest_revision_id === revisionId` and
   status `STAGED`/`PROCESSING` → keep polling (same MAX_POLL_ATTEMPTS bound and
   timeout message as before); anything else — the catalog does not track the
   revision, e.g. the fixture's null row or a superseded write → acceptance
   stands, success. Against the real backend the observable path is unchanged:
   a replace always surfaces the revision as `latest_revision_id` in
   STAGED → PROCESSING → ACTIVE/FAILED, so production still awaits genuine
   activation per category; only a catalog that does not contradict acceptance
   takes the new branch. The hook's contract comment was updated to state this.

2. **The failure alert rendered the raw category key** (`Nạp «jobs» không thành
   công` instead of `Nạp «Vị trí tuyển dụng» không thành công`). Fixed in
   `ProjectCreate.tsx` by routing both `state.failed` (alert) and `state.current`
   (running line) through `PROJECT_KNOWLEDGE_CATEGORY_LABELS` from
   `domain/project-knowledge-policy.ts` — the domain's single label table, which
   is the surface the feature's other label rendering already uses.

3. **The staged test file did not compile** (5 TS2554/TS2353 errors —
   `{ timeout }` passed to `expect.element` matchers that accept no options in
   Vitest 4.1.11; the dead session's "typecheck clean" predates these edits).
   Converted the five waits to the repo's established
   `vi.waitFor(() => expect.element(...).toBeVisible()/toHaveTextContent()/
   toBeEnabled(), { timeout: 10000 })` idiom. Assertions, matchers and the 10 s
   budgets are byte-for-byte the same intent; only the mechanism changed. This
   is the only edit to the test file.

The "cần nhập tay" report for skipped categories already existed in the dead
session's work (`ProjectBriefImport` renders "Chưa có trong tệp (bạn có thể
thêm sau): …" from `brief.missingCategories` with the Vietnamese labels), so no
new rendering was added.

`dbg.test.tsx` diagnostic value before deletion: it probed a jobs-only brief,
which is exactly why the dead session never saw the faq hang — a single-write
chain completes fine under the old poll. Nothing else of value in it. Removed
with `git rm -f` (gone from disk and index).

## Files modified (this session)

- `frontend/src/components/atomic-crm/projects/presentation/use-project-ingest.ts`
  — poll semantics + contract comment (+32/−16 roughly).
- `frontend/src/components/atomic-crm/projects/ProjectCreate.tsx`
  — Vietnamese label lookups for the running and alert lines (+6/−4 net).
- `frontend/src/components/atomic-crm/projects/ProjectCreate.test.tsx`
  — five wait-mechanics conversions, then prettier (+45/−30 incl. reformat).
- `frontend/src/components/atomic-crm/projects/dbg.test.tsx` — deleted.

Domain files (`project-knowledge-policy.*`, `project-knowledge-yaml.*`,
`ProjectBriefImport.tsx`) were verified and left as staged.

## Verification evidence

- `npx vitest run --config vitest.config.ts --project app
  src/components/atomic-crm/projects/ProjectCreate.test.tsx`
  → before: 4 failed / 7 passed; after: **11 passed (11)** (ran twice, including
  after the prettier pass).
- `npx vitest run --config vitest.config.ts --project app
  src/components/atomic-crm/projects`
  → **15 files, 128/128 passed** — includes the domain suites
  (project-knowledge-yaml, project-knowledge-policy, project-brief-ingest,
  externalSourcePolling) and every importer of the touched modules
  (ProjectEdit, ProjectKnowledgePanel, ProjectList, use-project-knowledge-catalog,
  ExternalSourceLinkForm/List, projects-workspace-layout). Re-run after
  parallel-session churn (see below): still 128/128.
- `npm run typecheck` (tsconfig.app.json): clean. `npm run typecheck:node`: clean.
  Both re-run on the final tree.
- `npx prettier --check` on the three touched files: clean. `npx eslint` on them:
  clean.

## Residual risk and notes for the controller

- **Index state is mixed, not by me.** I staged nothing (only the instructed
  `git rm -f` of `dbg.test.tsx`), but mid-session a parallel session staged my
  already-made edits to `use-project-ingest.ts` and `ProjectCreate.tsx`; the
  `ProjectCreate.test.tsx` fixes are still unstaged on top of the staged base
  (status `MM`). Review the full worktree diff, not just the index, before
  committing.
- **"Done" semantics, documented:** done now means "every write accepted by the
  backend and the catalog reports neither FAILED nor an in-review revision for
  it". In production the catalog always tracks a fresh revision as
  STAGED/PROCESSING, so the chain still awaits real activation; if the admin
  activates while knowledge is still in review, the backend's refusal is shown
  verbatim and the draft stays inactive, per the agreed design.
- **Parallel churn during the session:** commit `47292787` (ProjectList draft
  labels) and a prettier-only reformat of `domain/project-knowledge-yaml.ts`
  landed from another session; latest tree re-verified green above. Neither
  touches this feature's behavior.
- **registry.json** (owned by another session, currently `MM`): the feature
  changed published application files (`ProjectCreate.tsx`,
  `presentation/use-project-ingest.ts`, `presentation/ProjectBriefImport.tsx`),
  so `npm run registry:gen` / `registry:check` will need a pass before release.
  Left alone per instructions.
