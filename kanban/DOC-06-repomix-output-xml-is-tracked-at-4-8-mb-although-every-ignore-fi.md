---
id: DOC-06
title: "repomix-output.xml is tracked at 4.8 MB although every ignore file classifies it as generated"
severity: high
area: docs
labels: [documentation, tech-debt]
effort: S
status: todo
found: 2026-09-24
---

# DOC-06 — repomix-output.xml is tracked at 4.8 MB although every ignore file classifies it as generated

**Severity:** high · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt

## Problem

A 4.8 MB stale text dump of the whole repository is tracked, while `.openwikiignore` lists it under generated artifacts and repomix's own header says it honours `.gitignore`. The dump predates the AgentKit install, so it mirrors a tree that no longer exists.

## Evidence

- `repomix-output.xml` is a literal entry in `.git/index`, between `plans/reports/260724-1720-smoke-lead-context-completion.md` and `scripts/agent/test-project-guard.py`, and is 4.8 MB at the repo root.
- `.gitignore` has no `repomix` rule, but `.openwikiignore:31-33` lists `.repomix*` and `repomix-output.xml` under "Build output / caches / generated artifacts".
- Staleness proof: the dump's `<directory_structure>` shows `.claude/` containing exactly `hooks/project-guard.py` and three skills, whereas the index shows 1,858 `.claude` files including 106 `ak-*` skills — and `project-guard.py` no longer exists.
- Residual leak check: the only credential-shaped hit is `repomix-output.xml:72529-72530` → `JWT_SECRET=change-me-please-32-chars-minimum-aaaa`, i.e. `.env.example` content; `backend/.env` is not in the dump.

## Impact

4.8 MB per clone for a stale mirror of the tree, plus a duplicate-context trap where an agent reads the old copy instead of the source, plus a standing risk that a future repomix run with a looser ignore config commits real env content.

## Suggested fix

Add `repomix-output.xml` and `.repomix*` to `.gitignore`, then `git rm --cached repomix-output.xml` and commit; keep future dumps outside the repo (`--output /tmp/repomix.xml`).

## Notes

Merge with DOC-07 — same class (generated or stray artifact tracked); the `.gitignore` rules belong in one commit.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
