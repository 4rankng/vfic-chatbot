# Agent Completion Checklist

## Task record

- Task: Close tech-debt cards DOC-04 (plans/ ignored while the completion mandate points there), DOC-05 (three agent-config trees, 1,858 tracked `.claude` files, hook running twice per prompt) and DOC-12 (config duplication), inside the DocsProcess file slice.
- Scope: `plans/**`, `.claude/**`, `.omc/**`, `CLAUDE.md`, the agent-config sections of `AGENTS.md`, `.husky/**`, `package.json` files, `docs/agent-development-kit.md`. Root `.gitignore` and `docs/**` belong to DocsHygiene in this wave and were coordinated by message, not edited here.
- Files changed: `.claude/settings.json` (deduped `UserPromptSubmit`), `.claude/hooks/hooks.json` (deleted), `docs/agent-development-kit.md` (hooks layer, guard behaviour, verification, new configuration-authority section), `AGENTS.md:12` (single code-convention pointer), `frontend/.husky/pre-commit` (make dependency removed), `plans/.omc/` (deleted runtime-state duplicate), plus this record.
- Instructions retrieved: the three kanban cards, `AGENTS.md`, `standards/agent-completion-checklist.md`, `standards/coding-style.md`, `docs/code-standards.md`, `.gitignore`, `.agentkit/config.yaml`, `.agentkit/adapters/claude-code/engineer/.agentkit/{native-skill-paths,native-hook-expectations}.json`, `.claude/settings.json`, `docs/qa-runbook.md`.
- Approval required: no. `AGENTS.md` lists dependency manifests, deployment files and Makefiles as approval-gated; the root `Makefile`, `backend/Makefile`, `backend/pyproject.toml`, `backend/docker-compose.yml` and the Caddy template were not touched.
- Approval evidence: N/A — no gated path was modified.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | DOC-05 dedupe verified: `python3 -c "...json.load('.claude/settings.json')..."` → `events: 8 invocations: 19`, `UserPromptSubmit entries: 1 hooks: 4` (was 2 entries / 6 invocations, 21 total). Deleted manifest proven redundant: per-event script sets of `.claude/hooks/hooks.json` were a subset of `.claude/settings.json` (`hooks.json scripts NOT already registered by settings.json: {}`). |
| Diff is limited to the approved scope | PASS | Every edited path is in the ownership list. `.gitignore` (DocsHygiene) changed by them after my message; `frontend/package.json` untouched; no `backend/`, `standards/`, `docs/` (other than `docs/agent-development-kit.md`) or `kanban/` write. |
| Protected operations were avoided or approved | PASS | No `git`, no deploy, no formatter, no test-suite run, no dependency added. `backend/Makefile`, root `Makefile`, `backend/pyproject.toml` untouched (owned by other slices this wave). |
| Focused tests/checks pass | PASS | `sh -n frontend/.husky/pre-commit` → OK; referenced artifacts exist (`frontend/.lintstagedrc`, `frontend/.prettierrc.json`, `frontend/registry.json`, `package.json` script `registry:gen`). Ignore patterns verified with the vendored gitignore engine (`node -e` on `.claude/hooks/scout-block/vendor/ignore.cjs`): `plans/reports/…` false, `plans/qa-2026-09-24/report.md` false, `plans/260922-0945-custom-context-window/plan.md` true. |
| Broader regression tests pass when shared behavior changed | N/A | No product code, API, schema or test surface changed; the only behavior change is hook registration inside `.claude/`, which the repository has no test for (the doc now records that `scripts/agent/test-project-guard.py` does not exercise it). |
| Lint passes for affected code | N/A | No source file changed; project linting is run centrally by the orchestrator per this wave's rules. |
| Type checking passes for affected code | N/A | Same as above; edited artifacts are JSON, Markdown and one shell hook. |
| Build/import validation passes for affected code | PASS | `.claude/settings.json` parses (all 14 registered scripts exist on disk: `registered scripts missing on disk: []`); deleted `hooks.json` is referenced by no loader (see Documentation impact). |
| Security and privacy impact reviewed | PASS | Removed a duplicate registration of `secret-output-guardrail.cjs`; the hook still fires once per prompt, so no privacy guard was weakened. `privacy-block.cjs` and `scout-block.cjs` registrations untouched. No secret was read, written or printed. |
| Performance and async-I/O impact reviewed | PASS | Prompt-time hook spawns drop from 6 to 4 per prompt (two-node-invocation reduction) with no dependency between events; total registrations 21 → 19. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | The rewritten `frontend/.husky/pre-commit` fails fast if the repository root cannot be resolved instead of running `npm` in the wrong directory; command order and continue-on-failure semantics are otherwise preserved. |
| Documentation impact handled | PASS | `docs/agent-development-kit.md` now names `.claude/settings.json` as the single hook registration point, describes the real guard hooks, records that `scripts/agent/test-project-guard.py` targets an unregistered guard, and maps the authority of `.claude/`, `.agentkit/` and `.omc/`. `AGENTS.md:12` names one code-convention document. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. The unowned orphan `scripts/agent/test-project-guard.py` is disclosed in the doc and in the wave report rather than silently re-pointed. |
| Final `git diff --check` passes | N/A | Git use is forbidden for this slice; the orchestrator runs the central diff/status review. |
| Final `git status --short` reviewed | N/A | Same reason. Deletions applied on disk (`rm`) and therefore appear as unstaged deletions: `.claude/hooks/hooks.json`, `plans/.omc/`. |

## Result

- Overall status: PASS (three of DOC-12's six duplication pairs are owned by other slices in this wave: Makefiles, the Caddy template/compose pair and the JS lockfile. The lockfile pair is already resolved — `frontend/pnpm-lock.yaml` is gone from disk and from the index; `frontend/package-lock.json` is the surviving one.)
- Remaining risks or follow-ups: `ak kit init` can re-emit `.claude/hooks/hooks.json` from its plugin adapter, so a maintainer must re-delete it (documented in `docs/agent-development-kit.md`). `.claude/agents/`, `.claude/rules/`, `.claude/output-styles/`, `.claude/ak-engineer-statusline.cjs`, `.agentkit/config.yaml` and the newer `plans/reports/*` are un-ignored but not yet staged. Nested `.omc/` runtime copies remain under `frontend/` (×5), `backend/` and `kanban/`, outside this slice. `scripts/agent/test-project-guard.py` is still an orphan test for an unregistered hook; `scripts/` belongs to no slice in this wave.
