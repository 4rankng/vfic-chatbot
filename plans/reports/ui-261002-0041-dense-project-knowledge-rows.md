# Dense project knowledge rows (projects directory)

Date: 2026-10-02 · Branch: main · Commit: d8977259 · Deploy: `make deploy` (owner-authorized)

## Outcome

The expanded project row in the projects directory collapsed from five
single-item stacked rows (actions, KB export strip, section title, legend,
template button + readiness counter) to two dense bands plus the category
workspace, following the Untitled UI page-header anatomy (title/legend left,
controls right, border as divider):

- One operations row: `Sửa / Tắt / Xóa` lead left, `KB đang sử dụng ·
  Markdown (.md)` + `Xuất KB` right. Implemented as an optional `toolbar`
  slot on `ProjectKnowledgePanel`; `ProjectList` passes the actions through
  it instead of rendering its own row.
- One section band: `Kiến thức theo danh mục` + legend `Việc làm có trong
  file = đang tuyển.` left, readiness counter + `Tải mẫu KB` right, the
  band's border-bottom replacing the counter row's own divider.
- Desktop content gaps tightened (knowledge content 20→16px, expanded
  content 18px/20-28px → 12px/16-20px padding).
- Mobile (<768px) keeps a stacked flow via grid areas on the header
  (title row / legend row / counter+template row). Copy, controls, and
  control heights unchanged (40px desktop cap respected).

## Files

- `frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx` —
  `toolbar?: ReactNode` slot, toolbar row render, header band restructure.
- `frontend/src/components/atomic-crm/projects/ProjectList.tsx` — actions
  moved into the `toolbar` slot.
- `frontend/src/components/atomic-crm/projects/ProjectList.test.tsx` —
  panel mock renders the toolbar (signature parity with the real panel).
- `frontend/src/components/atomic-crm/projects/projects.css` — header band,
  toolbar row, progress counter, mobile grid areas; new rules scoped under
  `.inbox-bg-container.project-workspace` (FE-19 ratchet unaffected: cap
  counts only the forbidden descendant form, which did not grow).

## Validation

- `npm run typecheck` — clean.
- eslint + prettier on changed files — clean (pre-commit lint-staged also ran).
- vitest browser: ProjectList, ProjectKnowledgePanel, ProjectKnowledgeExport,
  projects-workspace-layout, ProjectEdit, project-recruitment-responsive,
  css-scoping — 71 passed, 0 failed.
- `registry:gen` — manifest unchanged.
- First mock-based run exposed a real regression risk: nesting the actions
  inside the panel means the panel's mock must render the toolbar; caught by
  the disabled-toggle tests before commit.

## Notes / open items

- TEST-10 applies: CSS assertions are source-text only; visual QA of the
  expanded row (desktop + phone width) is the standing manual step.
- The MCP PRO catalog search confirmed the composed-header anatomy; no new
  Untitled UI component was warranted — installed primitives only.
