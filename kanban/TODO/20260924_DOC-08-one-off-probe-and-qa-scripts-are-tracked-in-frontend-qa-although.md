---
id: DOC-08
title: "One-off probe and QA scripts are tracked in frontend/qa although the backend explicitly bans the practice"
severity: medium
area: docs
labels: [documentation, testing]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# DOC-08 — One-off probe and QA scripts are tracked in frontend/qa although the backend explicitly bans the practice

**Severity:** medium · **Area:** docs · **Effort:** S · **Labels:** documentation, testing

**Trạng thái:** TODO

## Problem

`frontend/qa/` tracks ten `probe-*.cjs`/`qa-*.cjs`/`ultraqa-sweep.cjs` leftovers plus `TEST_PLAN.md` and a generated `registry.json`, while `backend/.gitignore` states the opposite policy for the same artifact class in its own tree.

## Evidence

- Tracked in `frontend/qa/`: `probe-debug.cjs`, `probe-menu.cjs`, `probe-profile.cjs`, `probe-qc.cjs`, `probe-users.cjs`, `probe-users2.cjs`, `qa-audit.cjs`, `qa-audit2.cjs`, `qa-smoke.cjs`, `ultraqa-sweep.cjs`, `TEST_PLAN.md`.
- Also tracked and one-off or generated: `frontend/scripts/harness-monitor.mjs` (23.0 KB), `launch-harness.sh`, `clean-harness.sh`, `generate-registry.mjs`, `check-registry-paths.mjs` and `frontend/registry.json` (29.7 KB).
- `backend/.gitignore:24-27` — "Local one-off debug / probe scripts (hardcoded dev paths; not rebuildable in the Docker image, so they must never ship)" → `/probe_minimax_digest.py` and `/retry_lgdisplay.py` are ignored.

## Impact

Two contradictory policies for the same artifact class: the frontend copies are agent/QA leftovers, any hardcoded local path in them is a footgun for the next reader, and `registry.json` is shipped generated output.

## Suggested fix

Adopt the backend policy: `git rm --cached frontend/qa/probe-*.cjs frontend/qa/qa-audit*.cjs frontend/qa/ultraqa-sweep.cjs frontend/registry.json`, then add `frontend/qa/probe-*.cjs`, `frontend/qa/qa-audit*.cjs` and `frontend/registry.json` to `.gitignore`; keep `TEST_PLAN.md` and the two harness scripts if they are genuinely reusable.

## Notes

Merge with DOC-10 — the same repo-hygiene pass over tracked stray artifacts.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
