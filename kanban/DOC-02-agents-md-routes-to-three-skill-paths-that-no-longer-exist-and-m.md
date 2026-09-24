---
id: DOC-02
title: "AGENTS.md routes to three skill paths that no longer exist and mis-paths the smoke script"
severity: high
area: docs
labels: [documentation]
effort: S
status: todo
found: 2026-09-24
---

# DOC-02 — AGENTS.md routes to three skill paths that no longer exist and mis-paths the smoke script

**Severity:** high · **Area:** docs · **Effort:** S · **Labels:** documentation

## Problem

The always-loaded constitution points at three `.claude/skills/*` paths that have been deleted, at a `.omc/skills/` directory that contains no skills, and at `scripts/smoke_turn.py` when the file lives at `backend/scripts/smoke_turn.py`. The same broken-hook claim appears in `docs/agent-development-kit.md`.

## Evidence

- `AGENTS.md:71` → `.claude/skills/implement-change/SKILL.md`, `:72` → `.claude/skills/verify-change/SKILL.md`, `:73` → `.claude/skills/qa-dev-environment/SKILL.md` — all three missing from the tree.
- `AGENTS.md:75` — "relevant `.omc/skills/` expertise"; `.omc/` contains only `project-memory.json`, `state/` and `sessions/`, with no `skills/` at all.
- `AGENTS.md:78` — "passes `scripts/smoke_turn.py`"; the actual path is `backend/scripts/smoke_turn.py`.
- `docs/agent-development-kit.md:16-17` names `.claude/hooks/project-guard.py`, which does not exist, while `.claude/settings.json` registers `descriptive-name.cjs`/`privacy-block.cjs`/`scout-block.cjs`; the doc's verification command at `:38` (`scripts/agent/test-project-guard.py`, which *is* tracked) therefore tests an unwired guard.
- The three repo skills survive only inside the stale `repomix-output.xml`; the live `skills/` tree is 106 vendor `ak-*` directories, so the discovery path works and the targets are simply gone.

## Impact

Implementation, verification and QA routing — the three primary workflows — dead-ends on the first tool call, so agents improvise instead of following repo procedure.

## Suggested fix

Repoint `AGENTS.md:71-75` at real targets (`.claude/skills/ak-cook/`, an `ak-debug` or verification equivalent, `standards/agent-completion-checklist.md`) or restore the three repo skills; fix the `backend/scripts/smoke_turn.py` path at `AGENTS.md:78` and the two claims in `docs/agent-development-kit.md:16,38`.

## Notes

Merge with DOC-05 — the same missing `project-guard.py` and the same `.claude` tree.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
