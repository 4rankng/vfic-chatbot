# Users table fix — record context + header band

Date: 2026-09-30 ~22:00–23:30+08 · Work context: `/Volumes/LexarSSD/projects/chatbot`
Frontend working tree, branch `main`, uncommitted (controller commits).

## What changed (4 files)

### 1. `frontend/src/components/atomic-crm/kit/list-table.tsx` — the diagnosed fix
- Every cell body is now wrapped in react-admin's `RecordContextProvider`
  (import added). The wrap sits **inside the Row's children function**, around
  `{column.cell(record)}` — not around the `Table.Row`.
- Why there: the first cut wrapped `Table.Row` in the item renderer, and the
  kit test failed with **real ra-core**: React Aria builds its collection in a
  hidden pass and renders the real DOM rows from collection nodes, so a
  provider around the row exists only in the hidden pass and never wraps the
  rendered cells. Inside the children function the provider is part of what RAC
  actually renders into the `<td>`. Evidence: kit test `hands each row's record
  to cells that read the record context` failed before the relocation and
  passes after (real `useRecordContext`, no mocks).
- Doc comment updated. No API change; only consumer of `ListTable` is
  `users/UserList.tsx` (grep-verified; cell wiring untouched per constraint).

### 2. `frontend/src/components/application/table/table.tsx` — header band fix
- `TableRow` base classes: `after:pointer-events-none` → `after:hidden`, with a
  comment explaining the mechanism.
- **Mechanism (reproduced causally in real Chromium via the Vite dev-server
  page, screenshots in /tmp):** any Tailwind `after:` utility forces
  `content` onto the row's own `::after`. A generated box inside a `<tr>` is
  wrapped in an anonymous table cell → a phantom auto grid column. With
  `table-layout: fixed` + `width: 100%`, the two real auto columns and the
  phantom split the leftover 3 ways: 686/3 ≈ 228.7px each — the header band
  stopped at 970.3 of 1198px while zebra rows (painted by the `tr`
  background) looked full width. Injecting `tr::after{display:none}` moved
  both to 1199 (full width); undoing it restored 970.3 — causal proof. The
  same classes on a static table (no RAC row pseudo) fill the width fine.
- Verified live: after the edit (Vite HMR), header cells end at 1199 = body
  cells = table width; second screenshot confirms the muted band reaches the
  right edge. Only consumer of this `Table` is the kit's `ListTable`
  (grep-verified), so blast radius is the same tables.

### 3. `kit/list-table.test.tsx` — two new regression tests
- `hands each row's record to cells that read the record context`: a no-props
  cell component (`useRecordContext`-only) renders each row's role; fails when
  the context is missing (the production symptom).
- `never generates a box from the row's own ::after`: source-text pin on
  `table.tsx`'s `TableRow` (via `?raw` import, the repo's established pattern
  where the vitest lane cannot render the mechanism — the lane loads no
  Tailwind, so the phantom column is invisible in rendered output there).
- Replaced the debug/DOM-dump scaffold used during investigation with the
  tests above.

### 4. `users/UserList.test.tsx` — the test gap that hid the bug
- Root cause of the miss: the whole-module ra-core mock stubbed
  `useRecordContext: () => listState.data[0]`, so the badges rendered in tests
  while rendering `null` in production. The mock now spreads
  `importOriginal` (repo's ProfilePage/ProjectKnowledgePanel idiom) and
  deliberately does NOT stub `useRecordContext` (comment records the ruling).
- Tightened: asserts the record-driven chips render per row —
  `Tuyển dụng` / `Quản trị` role chips and `Hoạt động` / `Vô hiệu` status
  chips, exact-matched (`exact: true` — "Quản trị" otherwise substring-matches
  the page heading's "Quản trị truy cập" eyebrow).

## Files NOT touched
- `users/UserList.tsx` cell wiring, `users.css`, `account-layout-regressions.test.tsx`
  (covers `UserCreate` form only — unrelated), `users.css` untouched.
- `account-layout-regressions.test.tsx` passes unchanged (5 tests).

## Verification (exact commands, from `frontend/`)
| Command | Result |
|---|---|
| `npm run typecheck` | clean |
| `npm run test:unit:app -- kit/list-table.test.tsx UserList.test.tsx account-layout-regressions.test.tsx SettingsConsolePage.navigation.test.tsx` | **31/31 pass** (4 files) |
| `npm run lint` | 0 errors (36 pre-existing warnings, none in the 4 changed files) |
| `npm run prettier` | the 4 changed files **clean** under repo prettier 3.6.2; gate still fails on 12 files **outside this task** (`e2e/vfic.spec.ts`, integrations/*, form-controls*, ForgotPasswordPage, project-knowledge-yaml*, ProjectEdit.test, ProfilePage.test, account-layout-regressions.test.tsx, UserActions.tsx) — pre-existing/parallel-session drift, not introduced here |
| Live Chromium (dev server :5173, agent-browser, real Tailwind) | header band and body rows both end at 1199/1199px; before-fix measurement: 970.3 vs 1198 |

## Constraints honoured / notes
- No commit made (controller commits). Browser session closed; no processes
  started or killed; dev DB untouched (login attempt with e2e creds failed
  harmlessly — the e2e harness only ever touches `*_e2e` databases).
- `after:hidden` on `TableRow` affects only `ListTable` surfaces (sole
  consumer of `application/table`).
- Consumers of `ListTable` re-audited: only `users/UserList.tsx`; no consumer
  can break from gaining a record context (additive).
- Prettier note: an `npx prettier` (newer than the repo's 3.6.2) briefly
  reformatted unrelated hunks in table.tsx; all unrelated churn was reverted
  by hand; final state verified with the repo's own 3.6.2.

## Unresolved / flagged
- The vitest lane loads no Tailwind, so the phantom-column mechanism has no
  rendered-output regression lane; the new source-pin test is the guard.
  If the row pseudo is ever reintroduced, the header band breaks silently.
- The prettier gate failing on 12 unrelated files is pre-existing tree drift
  (other in-flight sessions); flagging so it isn't attributed to this change.
