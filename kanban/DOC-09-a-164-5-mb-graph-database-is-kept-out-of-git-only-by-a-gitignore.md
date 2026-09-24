---
id: DOC-09
title: "A 164.5 MB graph database is kept out of git only by a .gitignore inside its own untracked directory"
severity: medium
area: docs
labels: [documentation, tech-debt]
effort: S
status: todo
found: 2026-09-24
---

# DOC-09 — A 164.5 MB graph database is kept out of git only by a .gitignore inside its own untracked directory

**Severity:** medium · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt

## Problem

`.code-review-graph/graph.db` is 164.5 MB and correctly untracked, but the only rule keeping it out of git lives at `.code-review-graph/.gitignore` — inside the untracked directory itself. There is no root `.gitignore` rule, so a regenerated graph at a different path, or a tool that writes the DB before its `.gitignore`, would let `git add -A` pick up 164.5 MB.

## Evidence

- `.code-review-graph/graph.db` — 164.5 MB, absent from `.git/index`; ignored only by `.code-review-graph/.gitignore:1-3` (`*`, "do not commit database files").
- `.agentkit/ownership.json` 479.3 KB and `.agentkit/script-audit.json` 218.0 KB — untracked via root `.gitignore:9` plus `.agentkit/.gitignore`.
- Root `.omc/**` plus 8 nested copies (~40 files), `backend/vfic_backend.egg-info/`, `backend/.pytest_cache/`, `backend/.ruff_cache/` (incl. `0.15.22/`), `plans/.ruff_cache/`, `frontend/test-results/`, `frontend/.vitest-attachments/` (123.5 KB) and four `**/__screenshots__/` directories are all correctly untracked (root `.gitignore:66-68`, `backend/.gitignore`, `frontend/.gitignore:14,20`, `.gitignore:75`).
- Byte totals are measured from directory listings; the `.claude/**` working-tree size is **[EST]** (~11 MB, sampled from one module) and needs `du -sh .claude`.

## Impact

No clone cost today, but a real guardrail gap: the single most dangerous file in the working tree is protected by a rule that is itself untracked, so a path change or a write-ordering difference turns the next `git add -A` into a 164.5 MB commit. The MB-scale artifacts also cost local disk for no benefit.

## Suggested fix

Add `.code-review-graph/` to the root `.gitignore` and delete the MB-scale files when unused (`rm -rf .code-review-graph/graph.db .agentkit/ownership.json .agentkit/script-audit.json`), then add a periodic `git clean -ndX` review.

## Notes

Merge with DOC-06/DOC-07 — all three are `.gitignore` hardening for artifacts the repo should never track.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
