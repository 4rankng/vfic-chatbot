---
id: DOC-05
title: "Three parallel agent-config systems, 1,858 tracked .claude files, and a hook that runs twice per prompt"
severity: high
area: docs
labels: [documentation, tech-debt]
effort: M
status: todo
found: 2026-09-24
---

# DOC-05 — Three parallel agent-config systems, 1,858 tracked .claude files, and a hook that runs twice per prompt

**Severity:** high · **Area:** docs · **Effort:** M · **Labels:** documentation, tech-debt

## Problem

`.claude/`, `.agentkit/` and `.omc/` are three competing sources of agent configuration with conflicting ignore rules; 1,858 `.claude` files are tracked while the subdirectories the team actually runs are not. `.claude/settings.json` and `.claude/hooks/hooks.json` register the same 13 hooks, and in both files the `UserPromptSubmit` block is duplicated.

## Evidence

- `.gitignore:44` ignores `/.claude/*` with only `/settings.json`, `/hooks/**` and `/skills/**` re-included (`:45-49`), so `.claude/agents/` (16 files), `.claude/rules/` (8), `.claude/output-styles/` (6), `.claude/ak-engineer-statusline.cjs` and `.claude/hooks/.logs/` sit on disk but are untracked.
- Tracked counts from the index `TREE` cache: `.claude` = 1,858 entries / 2 subtrees, `.claude/skills` = 1,801 entries / 106 subtrees, `.claude/hooks` = 56 entries / 3 subtrees.
- `.agentkit/` holds `ownership.json` (479.3 KB) and `script-audit.json` (218.0 KB); its `config.yaml` header says it is "meant to be committed" and `.agentkit/.gitignore` does `*` + `!config.yaml`, but root `.gitignore:9` wins — conflicting sources of truth for one directory. `.omc/` exists in 9 copies (`.gitignore:53`) and `AGENTS.md:75` still points at "`.omc/skills/`", which does not exist.
- `.claude/settings.json` and `.claude/hooks/hooks.json` register the same 13 hooks (one via `${CLAUDE_PROJECT_DIR}`, one via `${CLAUDE_PLUGIN_ROOT}`), and **both** duplicate the `UserPromptSubmit` block — two entries with `"matcher": "*"` each invoking `secret-output-guardrail.cjs`, with `simplify-gate.cjs` in both — so those hooks execute twice per prompt.
- `docs/agent-development-kit.md:16-17` points at `.claude/hooks/project-guard.py`, which does not exist.

## Impact

A fresh clone gets 1,858 vendor files but not the agents, rules and styles the team actually runs, and gets hook registrations whose duplicate `UserPromptSubmit` entries double prompt latency and token spend. Nobody can tell which tree is authoritative.

## Suggested fix

Pick one policy and encode it in `.gitignore`: either keep the vendor kit out of the product repo (ignore `.claude/skills/` and `.claude/hooks/`, commit only `settings.json` plus a pinned install script), or commit all three layers and drop the `/.claude/*` un-ignore maze. Either way, delete the duplicated `UserPromptSubmit` entry in `.claude/settings.json` and `.claude/hooks/hooks.json` (and `hooks.json` itself if `settings.json` is the live file), drop the `plans/`→`.omc` copies, and fix or delete `docs/agent-development-kit.md:16,38`.

## Notes

Merge with DOC-02 (same missing `project-guard.py`) and DOC-12 (the two hook configs are also a duplication finding).

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
