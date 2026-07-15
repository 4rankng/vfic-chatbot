---
date: 2026-07-15
session: agent-development-kit
---

# Journal: 2026-07-15 — Repository agent development kit

## Context

The repository's agent instructions had grown into an always-loaded operating
manual with duplicated project guidance. The goal was to keep durable policy
visible to every coding agent while moving task detail and mechanically
detectable safety checks into narrower, versioned layers.

## What happened

- Root `AGENTS.md` became the concise constitution: project boundaries,
  approval gates, protected operations, and essential verification. Root
  `CLAUDE.md` imports it so Claude Code and AGENTS-aware tools share that policy.
- Repository skills now load implementation, verification, and development-QA
  workflows on demand and route agents to existing source-of-truth documents
  instead of copying those documents into startup context.
- A shared `PreToolUse` hook classifies recognized edits and shell commands.
  Secret-file writes and clearly destructive Git/filesystem operations are
  denied; protected but potentially legitimate work returns `ask` for explicit
  approval. Ordinary operations remain silent and use normal permissions.
- `.claude/settings.json`, hooks, and project skills are versioned for the team.
  Personal permissions and experimental state stay in the ignored
  `.claude/settings.local.json`.

## Decisions

| Decision | Rationale | Impact |
|---|---|---|
| Separate constitution, skills, and hooks | Persistent policy, task expertise, and deterministic checks have different context and reliability needs | Startup context stays small without losing repository guardrails |
| Use `deny` only for prohibited or destructive operations | These actions should not proceed through routine approval | Secret writes and recognized destructive commands stop immediately |
| Use `ask` for protected operations | Migrations, deployment, dependencies, prompts, and security-sensitive files can be valid with human intent | The hook pauses work without replacing the constitution's broader judgment rules |
| Version shared configuration and ignore local state | Team policy must be reproducible; personal permissions must remain private | Contributors share the same guard and skills without committing workstation choices |

## Verification

- `python3 scripts/agent/test-project-guard.py`: 33 fixtures passed, covering
  allowed reads/edits, secret denials, protected-file approval, command
  variants, destructive operations, redirection, and malformed input.
- `.claude/settings.json` parsed successfully as JSON.
- The scoped agent-kit diff passed `git diff --check`.

## Limitations/Next

The hook is a workflow guardrail, not a shell sandbox. It classifies the literal
pre-execution command, so variable indirection or other dynamic command
construction can obscure a protected target. Semantic risks such as an
incompatible API change also cannot be inferred reliably from paths alone.
Agents must therefore continue following `AGENTS.md` when the hook is silent.
Keep adversarial fixtures current as new command shapes or protected operations
are identified. Independent review closed all direct bypasses found in scope.
