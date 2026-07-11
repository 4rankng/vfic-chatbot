# Lessons Learned — AI Knowledge Base

> Durable documentation of important discoveries, bug fixes, and engineering
> lessons. Both humans and AI agents retrieve from this instead of relying on
> conversation history.

## Why This Exists

Conversation history is ephemeral. When an agent discovers why a Zalo signature
fails, or why the LLM semaphore must cap at a specific value, that knowledge is
lost unless captured here. This knowledge base ensures important discoveries
persist across sessions, agents, and team members.

## How to Use

### For AI agents
- **Before implementing a task**, check if a relevant lesson exists here. It may save you from repeating a known mistake.
- **After discovering something non-obvious** (a tricky bug cause, an integration quirk, a performance gotcha), create a lesson file.

### For humans
- Browse lessons when onboarding or investigating a recurring issue.
- Link to lessons in PRs and commit messages when the change relates to a past discovery.

## File Naming Convention

```
lessons/YYYY-MM-DD-topic.md
```

- **Date:** the date the lesson was discovered (not the date it was written up).
- **Topic:** short kebab-case description (e.g., `openrouter-rate-limit`, `zalo-signature`, `payroll-forecast`).

Examples:
```
lessons/2026-07-11-openrouter-rate-limit.md
lessons/2026-07-12-zalo-signature-validation.md
lessons/2026-07-14-llm-semaphore-deadlock.md
```

## Categories

| Category | When to use |
|---|---|
| `architecture` | Discoveries about system structure, layering, dependency boundaries |
| `bug-fix` | Root cause of a non-obvious bug and the fix applied |
| `api-design` | Lessons about API contract design, response shapes, error handling |
| `deployment` | Deploy-related discoveries (env vars, Docker quirks, Caddy config) |
| `performance` | Performance bottlenecks found and their resolutions |
| `conventions` | Coding conventions that emerged from experience (not decided upfront) |

## Template

```markdown
# [Lesson Title]

- **Date:** YYYY-MM-DD
- **Category:** architecture | bug-fix | api-design | deployment | performance | conventions
- **Discovered by:** [human name or "AI agent"]
- **Severity:** low | medium | high | critical

## Context

[What were you trying to do? What was the situation?]

## Discovery

[What did you find? What was non-obvious? What was the root cause?]

## Impact

[What would happen if this wasn't known? Who/what is affected?]

## Action Taken

[What was done to fix or address this? Include file paths and commit/PR references.]

## Related

- [Code paths]: `backend/app/...`
- [Docs]: [`docs/...`](../docs/...)
- [ADRs]: [`docs/decisions/...`](../docs/decisions/...)
- [Other lessons]: [`lessons/...`](./...)
```

## Index

_No lessons recorded yet._ As discoveries are made, add them here in a table:

| Date | Topic | Category | Severity |
|---|---|---|---|
| _YYYY-MM-DD_ | _topic_ | _category_ | _severity_ |

## Guidelines

1. **Be specific.** "Zalo webhook HMAC validation fails when the secret has trailing whitespace" — not "webhooks can break."
2. **Include the root cause.** The symptom is less valuable than why it happened.
3. **Link to code.** Reference exact file paths so future readers (human or AI) can find the relevant code.
4. **Record what you tried that didn't work.** Negative results are valuable — they prevent others from repeating the same dead ends.
5. **Keep it concise.** One page per lesson. If a lesson needs more than 2 pages, it's probably multiple lessons.
6. **Don't duplicate existing docs.** If the lesson belongs in `docs/troubleshooting/` or an ADR, put it there and link to it from here.
