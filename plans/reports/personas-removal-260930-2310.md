# Personas page removal + persona code constant — 2026-09-30 23:10

Owner request: remove the `#/personas` admin page from TingHire; freeze the agent
persona as a backend code constant holding the pasted "Prompt Agent" content.
Branch `main`. Controller commits.

## Part 1 — Frontend removal (DONE)

Deleted `frontend/src/components/atomic-crm/personas/` (all components, domain,
application, infrastructure, presentation, personaService, tests, untracked
`__screenshots__` PNGs). Cross-feature import check: only two consumers existed —
`capabilities/kernel/index.tsx` (the resource itself) and
`integrations/EmbeddedSettingsSections.tsx` (the settings embed). No other
feature imported personas modules; `personas/domain/assignmentState.ts` had zero
consumers outside the directory.

Updated to the new five-resource runtime:

- `capabilities/kernel/index.tsx` — personas import, nav entry ("Agent"), resource contribution, `Bot` icon removed.
- `capabilities/static-recruitment-runtime.ts` — `kernel.resource.personas` + `kernel.navigation.personas` removed from `RESOURCE_IDS`/`NAVIGATION_IDS`.
- Tests: `kernel/index.test.ts`, `navigation-contract.test.tsx`, `mobile-overflow-navigation.test.tsx`, `static-recruitment-runtime.test.ts` — new counts/destinations.
- `layout/Layout.tsx` — `isPersonaWorkspace` branch removed.
- `layout/topbar/command-palette.tsx` — "Tạo Agent" action removed.
- `layout/workspace-nav-model.ts` — team section heading "Đội ngũ & Agent" → "Đội ngũ" (the Agent surface is gone); `workspace-shell.test.tsx` + mobile-overflow test updated to match.
- `providers/commons/vietnameseCrmMessages.ts` — `resources.personas` and top-level `personas` i18n blocks removed.
- `providers/commons/canAccess.ts` comment + `canAccess.test.ts` — personas example replaced with `users`.
- Settings console: `EmbeddedSettingsSections.tsx` (`AgentsSettingsSection` removed, docstring now "two pages"), `SettingsConsolePage.tsx` (case removed), `settingsNav.ts` (`settings-agents` id/nav-item/view-copy removed, six entries), `SettingsConsolePage.navigation.test.tsx` (persona mock removed), `featureLayout.test.ts` + `index.tsx` comments updated.
- `npm run registry:gen` regenerated — diff is removal-only (0+/72-); `registry:check` passes (231 files).

## Part 2 — Backend persona constant (DONE)

- NEW `backend/app/services/personas/constant.py` — `DEFAULT_PERSONA_NAME`
  ("VFIC Bot mặc định"), `DEFAULT_PERSONA_SLUG` ("default-vfic"),
  `DEFAULT_PERSONA_BODY_MD` = the pasted S1–S6 verbatim, mapped onto the
  persona editor's seven-section markdown convention (`### 1. Vai trò của tôi`
  … `### 6. …`, section 7 present — see §7 note). Leaf module, no imports, so
  `app.graph → app.services.personas.constant` adds no cycle (verified:
  importing `app.services.personas.service` loads zero `app.graph` modules;
  mirrors the existing `graph/adapters.py → services.personas.repository` edge).
- `backend/app/graph/prompts.py` — `AGENT_SYSTEM_PROMPT` now IS the constant;
  `backend/app/graph/persona.md` deleted. Fallback == seed == one canonical body.
- `backend/scripts/seed/personas.py` — the active default row seeds the
  constant (name/slug/body); the inactive "LG Display" preset row untouched.
- `backend/app/graph/context.py` — docstrings now say "code constant" instead
  of persona.md. `_PROMPT_TEXT_REVISION` was concurrently bumped "2"→"3" by
  another agent's in-flight work; the bump covers this release's prompt-text
  change, so I left it (no double bump). Not touching `runner.py`/`channels`.
- `backend/app/services/personas/service.py` — one docstring line (persona.md → code constant).
- NEW `backend/tests/test_persona_constant.py` — fallback == constant, seed
  default row == constant, preset row distinct.

### Section 7 ("Lưu ý thêm") — CONFIRMED from the authoritative export

Team-lead forwarded the owner's authoritative export
(`/Users/dev/Downloads/agent.md`, 8395 bytes). All seven sections are now
verified BYTE-FOR-BYTE against it: a parser extracts each section's "Đã viết"
value from the export and compares it to the constant's parsed sections —
`ALL 7 SECTIONS VERBATIM-MATCH`. §7 stays, verbatim. Two fidelity details from
the export that the earlier paste had flattened: §1's business-info block
carries real newlines (`Thông tin doanh nghiệp:` and `Tên đầy đủ:` each end a
line) — the constant matches; §4's export entry places its value above a bare
"Đã viết" marker with nothing after — the authored text is the same
"TUYỆT ĐỐI KHÔNG BỊA ĐẶT (NO HALLUCINATION)…" line the constant carries.
Constant headings keep the repo's numbered editor convention
(`### 1. Vai trò của tôi` … `### 7. Lưu ý thêm`), which is what the concurrent
party's test pins and `composePersonaMarkdown`/`parsePersonaMarkdown` require.

### Collision with a concurrent session — division CONFIRMED by team-lead

The concurrent session keeps `backend/tests/test_persona.py`,
`backend/tests/test_persona_voice.py` and the graph-side files (context.py,
config.py, vector.py, clients.py, lanes.py — I made no further edits there).
I keep `constant.py`, `prompts.py`, `seed/personas.py`, the persona.md
deletion, `test_persona_constant.py`, and the entire frontend removal.
Acceptance gate (their pins + my equivalence tests against the constant):
`cd backend && .venv/bin/python -m pytest tests/test_persona.py
tests/test_persona_voice.py tests/test_persona_constant.py -p no:randomly -q`
→ **31 passed**.

`backend/app/graph/context.py` carries 4 docstring lines from me ("persona.md"
→ "code constant" wording, consistent with prompts.py now using the constant)
plus the concurrent party's `_PROMPT_TEXT_REVISION = "3"` bump — the file is
theirs to commit; the controller should let those lines ride their pathspec.

## Deliberately left (follow-ups, not defects)

- `providers/rest/dataProvider.ts` `RESOURCE_PATH.personas` and
  `.knowledge_bases` aliases kept — mirrors d3cef323's precedent of keeping
  legacy REST aliases after admin pages disappear; the backend personas API
  stays.
- `conversations/inbox/personas-*.css`, `mobile-persona-editor.css` and the
  `inbox.css` @imports kept: they live in the conversations feature and
  `personas-responsive.css` still carries ≤760px rules other workspaces
  (knowledge header) rely on (see `responsive-workspace-layout.test.tsx`
  comments). Removing them is CSS-cascade surgery needing per-screen visual QA
  (TEST-10). Follow-up: rebalance those sheets into their owning workspaces.
- `layout/workspace-shell.tsx:181` selector still names `.persona-center-panel`
  and `css-scoping.test.ts` comments still list a persona root — d3 left the
  identical `.knowledge-*` residue; same cleanup pass.
- `atomic-crm/types.ts` Persona/AdapterPersonaAssignment types kept (shared
  file, d3 left removed-feature types too).
- `backend/app/capabilities/recruitment/definition.py` `frontend_resources`
  still names `"personas"` (and `"knowledge_sources"`) — runtime capability
  contract; changing it is a separate contract-bump decision.
- `backend/tests/test_architecture_boundaries.py` still lists the dead
  `personas` root + `personaService.ts` composition entry — string-only
  classifiers, tests pass; d3 left `knowledge` the same way.
- `kit/page-shell.tsx` comment mentions personas — kit/ is owned by
  users-table-fix, not touched.

## Verification

- Acceptance gate: `cd backend && .venv/bin/python -m pytest
  tests/test_persona.py tests/test_persona_voice.py
  tests/test_persona_constant.py -p no:randomly -q` → **31 passed**.
- Export fidelity: scripted byte-for-byte comparison of all 7 constant sections
  against `/Users/dev/Downloads/agent.md` "Đã viết" values → all match.
- Backend: `test_persona_resolver_convergence.py` (with the gate files) → 36
  passed; `test_architecture_boundaries.py` + `test_runtime_surface_inventory.py`
  → 23 passed; ruff check + format clean on touched files.
- Frontend: `typecheck` clean; `lint` 0 errors (36 pre-existing warnings, none
  in touched files); `prettier --check` clean after one fix;
  `registry:gen` removal-only; `registry:check` pass.
- Vitest (touched suites): kernel index, navigation-contract,
  mobile-overflow, static-runtime, workspace-shell, workspace-nav-model,
  canAccess, featureLayout, SettingsConsolePage.navigation, css-scoping → all
  pass (27 + 16 + 2 + 1).
- `node scripts/check-doc-links.mjs` → 34 paths / 4 make targets resolve.

## Backend files modified (for pathspec-scoped commits)

Mine to commit:

- `backend/app/services/personas/constant.py` (NEW)
- `backend/app/graph/prompts.py` (rewritten: AGENT_SYSTEM_PROMPT = constant)
- `backend/app/graph/persona.md` (DELETED)
- `backend/scripts/seed/personas.py` (default row seeds the constant)
- `backend/tests/test_persona_constant.py` (NEW)

Shared / not mine to commit:

- `backend/app/services/personas/service.py` — one docstring line (persona.md
  → code constant); mine, trivially committable with the block above.
- `backend/app/graph/context.py` — 4 docstring lines mine, revision bump +
  surrounding graph work belong to the concurrent session; they commit it.

## Docs updated

`frontend/AGENTS.md` (five resources, aliases paragraph + constant pointer,
tree, CSS-scoping count), `docs/development/code-standards.md` (5 resources),
`docs/ops/qa-runbook.md` (route row, CRUD list, exit checklist),
`docs/design/design-qa.md` (kit-migration screen list),
`docs/product/codebase-summary.md` (frontend tree + module table rows; the
backend `services/personas/` mention correctly stays — the service lives on).

Status: DONE
Summary: personas page fully removed (frontend five-resource runtime verified)
and the persona is a backend code constant wired into both the seed and the
graph fallback — all seven sections byte-verified against the owner's export
`/Users/dev/Downloads/agent.md`; acceptance gate 31 passed.
Concerns: `backend/app/graph/context.py` is a mixed diff (my 4 docstring lines
+ the concurrent session's revision bump and graph work) — they commit it;
persona-named CSS in conversations/inbox remains a visual-QA follow-up.
