---
id: DOC-04
title: "plans/ is gitignored while AGENTS.md and the completion checklist mandate writing reports there"
severity: high
area: docs
labels: [documentation, ops]
effort: M
status: todo
found: 2026-09-24
---

# DOC-04 — plans/ is gitignored while AGENTS.md and the completion checklist mandate writing reports there

**Severity:** high · **Area:** docs · **Effort:** M · **Labels:** documentation, ops

## Problem

`.gitignore` ignores `plans/`, yet `AGENTS.md` and `standards/agent-completion-checklist.md` instruct agents to copy completion records into `plans/reports/`. Eleven legacy reports remain tracked while six newer ones are untracked and will never be committed, and tracked docs link to ~10 plan directories that no longer exist.

## Evidence

- `.gitignore:8` ignores `plans/`; `.git/index` still contains 11 tracked `plans/reports/*.md` (the `260723-*` set plus `260724-1720`), while the working tree holds 17 reports — `260913-2335`, `260921-1055`, `260921-2153`, `research-260921-1953`, `260922-2141` and `260924-1416` are untracked.
- `AGENTS.md:61` — "Copy `standards/agent-completion-checklist.md` to `plans/reports/<YYMMDD-HHmm>-<slug>-completion.md`"; the same instruction appears at `standards/agent-completion-checklist.md:4`, and QA records are mandated at `docs/qa-runbook.md:430,511`.
- Dangling references include `docs/chatbot-latency-improvement-plan.md:24,102,330` (`plans/20260710-chatbot-performance/`), `:332` (`plans/2026-07-12-performance-endpoint-latency/`), `docs/design-tokens-warm-paper.md:223` (`plans/260710-1322-frontend-ui-ux-redesign/`), `docs/decisions/0010-provider-returned-agent-reasoning.md:44` and `docs/journals/260712-performance-endpoint-alembic-double-head.md:10`.
- All six surviving plan directories are already-shipped work, proven by the commit log in `.git/logs/HEAD`: `runner-lane-pipeline`→`40ee8f5`, `conversation-state-split`→`1ddfa99`, `knowledge-projection-seam`→`93e654e`, `settings-provider-panel`→`6d2655c`, `llm-income-typed-seam`→`83f4f23`, `custom-context-window`→`a5c4e21`.

## Impact

The mandated completion and QA evidence trail is invisible to git — no reviewable artifacts, no blame, no history for the last six reports — while 11 stale reports stay tracked and referenced docs point at deleted directories, so "check `plans/` for overlap" (`AGENTS.md:54`) yields either nothing or the wrong thing.

## Suggested fix

Decide the policy and encode it: either track `plans/` (remove `plans/` from `.gitignore:8`, `git add plans/`) or keep it local and repoint the convention at a tracked path such as `docs/reports/<YYMMDD-HHmm>-<slug>.md`. Then delete the six shipped plan directories — the work is in git history — and fix the ~10 dangling references; `git rm --cached -r plans/reports` if going the local route.

## Notes

Merge with DOC-11 and DOC-10 — `docs/journals/` is currently the only populated durable-record path because `plans/` is ignored and `lessons/` is empty.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
