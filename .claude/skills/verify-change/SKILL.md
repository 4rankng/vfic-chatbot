---
name: verify-change
description: Select and run the correct Ting Ting checks for changed backend, frontend, documentation, agent-policy, or cross-module files.
---

# Verify a change

Inspect the diff and run the narrowest relevant checks first. Read
`docs/testing.md` and `standards/definition-of-done.md` when code, test, build,
or runtime behavior changed; do not load them for unrelated documentation work.

- Backend: targeted pytest, then `.venv/bin/ruff check .`; use the broader pytest
  lane required by the touched contract.
- Frontend: targeted Vitest where possible, then `npm run lint`,
  `npm run typecheck`, relevant app tests, and `npm run build` for shared or
  production-facing changes.
- Agent kit: `python3 scripts/agent/test-project-guard.py`, JSON parsing, link
  checks, and `git diff --check`.
- Documentation only: validate links, commands, dates, and claims against the
  actual repository.

Never use a live development or production database for unit tests. Report every
failure honestly; fix the cause or mark the work incomplete.
