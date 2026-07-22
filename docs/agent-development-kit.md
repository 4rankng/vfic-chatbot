# Agent Development Kit

The repository separates agent behavior into three versioned layers. This keeps
startup context small and makes safety rules more reliable.

## Layers

1. **Constitution:** root `AGENTS.md` contains durable repository boundaries,
   approval gates, and pointers for task-scoped instruction retrieval. Root
   `CLAUDE.md` imports it so Claude Code and AGENTS-aware tools share the same
   policy.
2. **Skills:** `.claude/skills/` contains task-specific workflows that load on
   demand and route to existing source-of-truth documents.
3. **Hooks:** `.claude/settings.json` registers a `PreToolUse` guard implemented
   by `.claude/hooks/project-guard.py`.

Personal permissions and experimental settings belong in
`.claude/settings.local.json`, which remains ignored.

## Guard behavior

The hook reads Claude Code's JSON event from standard input and returns one of:

- no output for ordinary operations, leaving normal permission handling intact;
- `deny` for secret-file writes and clearly destructive Git/filesystem commands;
- `ask` for protected-file edits and recognized migration-creation, deployment,
  and dependency-management commands.

The hook is a workflow guardrail, not a security sandbox. Shell commands can be
constructed in many ways, and semantic changes such as an incompatible API
contract cannot be classified reliably from a path alone. The approval rules in
`AGENTS.md` still apply even when the hook stays silent.

## Verification

From the repository root:

```bash
python3 scripts/agent/test-project-guard.py
```

In Claude Code, `/hooks` shows the registered shared project hooks. The hook
configuration follows the official project settings and `PreToolUse` decision
contract documented at <https://code.claude.com/docs/en/hooks>.
