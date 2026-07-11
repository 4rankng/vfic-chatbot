# Prompt Library

> Reusable prompt templates for common AI-assisted engineering tasks.
> Use these for consistent results across Claude Code, Codex, and Gemini CLI.

## How to Use

1. Copy the prompt template for your task type.
2. Fill in the bracketed `[placeholders]`.
3. Provide the prompt to your AI coding agent.
4. Review the output against [`../review-checklist.md`](../review-checklist.md) before merging.

---

## Templates

### Feature Implementation

```
Implement [feature name] in [file path / module].

Context:
- This module owns [responsibility].
- Existing patterns: [reference 2-3 neighboring files].
- Dependencies: [what this feature depends on].

Requirements:
1. [specific requirement 1]
2. [specific requirement 2]
3. [acceptance criteria]

Constraints:
- Follow the coding conventions in AGENTS.md §5 and docs/code-standards.md.
- Async-first (backend) / strict TypeScript (frontend).
- Add tests following the existing pattern in [neighboring test file].
- Do not modify [files that must never be auto-edited].

Before declaring done:
- Run [test command] and confirm all tests pass.
- Run [lint/typecheck command] and confirm no errors.
- Update [relevant docs] if behavior changed.
```

### Bug Fixing

```
Fix the bug: [description of the bug].

Reproduction:
- [steps to reproduce]
- Expected: [expected behavior]
- Actual: [actual behavior]

Root cause analysis:
1. Locate the failing code using docs/troubleshooting/chatbot-response-path.html (if bot-related).
2. Identify the root cause — not just the symptom.
3. Write a test that reproduces the bug.
4. Fix the root cause.
5. Verify the test passes and no regressions.

Constraints:
- Do not disable tests to make them pass.
- Do not introduce side effects (see AGENTS.md §13 for approval gates).
- Match existing error-handling patterns in the module.
```

### Refactoring

```
Refactor [module/file] to [goal: e.g., extract repository pattern, reduce coupling, split god file].

Rules:
- Behavior must NOT change. This is a move-don't-rewrite refactor.
- One commit per logical step.
- All existing tests must pass after each step.
- No new public API contracts.
- Match the pattern in [reference implementation].

Approach:
1. Identify the pieces to move.
2. Create the target structure (new files/modules).
3. Move code verbatim (no logic changes).
4. Update imports.
5. Run tests after each step.
6. Remove dead code from the old location.

Constraints:
- Do not change function signatures.
- Do not rename public exports without updating all callers.
- See AGENTS.md §4 for architecture boundaries.
```

### Performance Optimization

```
Optimize [module/function] for [metric: latency / memory / DB queries / bundle size].

Current state:
- [measured current performance]
- [profiling evidence: e.g., N+1 queries, slow query, large bundle]

Target:
- [specific target metric]

Constraints:
- Production runs on a 2 vCPU droplet (see standards/performance.md).
- No blocking I/O on the async event loop.
- Do not sacrifice correctness for speed.
- Measure before and after — provide evidence of improvement.

Approach:
1. Profile and identify the bottleneck.
2. Optimize the hottest path first.
3. Re-measure to confirm improvement.
4. Add a regression test if the optimization is non-obvious.
```

### Security Review

```
Review [module/file/PR] for security issues.

Check against standards/security.md:
- Boot-time safety intact (JWT secret, CORS validation)
- Auth enforced on all non-public endpoints
- Input validated (Pydantic schemas)
- Webhook HMAC validation intact
- No secrets logged
- No SQL injection (parameterized queries)
- No SSRF (if making outbound HTTP requests)
- No prompt injection vectors (if processing external content)
- Rate limiting intact on auth endpoints

Report:
- [CRITICAL] [issue] — [file:line] — [remediation]
- [HIGH] [issue] — [file:line] — [remediation]
- [MEDIUM] [issue] — [file:line] — [remediation]
- [LOW] [issue] — [file:line] — [remediation]
```

### API Design

```
Design a new API endpoint: [METHOD /api/v1/path]

Purpose: [what this endpoint does]

Requirements:
- Auth: [get_current_user / require_admin / require_recruiter / public]
- Request: [body schema, query params]
- Response: [schema, status code]
- Errors: [404 if not found, 409 on conflict, 403 on forbidden]

Patterns to follow:
- Route file: backend/app/api/[resource].py (see existing routers for pattern)
- Service: backend/app/services/[domain]/ (business logic)
- Schema: backend/app/schemas/[resource].py (Pydantic v2)
- Model: backend/app/models/[entity].py (SQLAlchemy 2.x)

Constraints:
- Follow the layering: API → Service → Model. No business logic in the route.
- Domain errors in services, HTTPException mapping in API.
- Response envelope: { data: [...], total: N } for lists.
```

### UI/UX Review

```
Review [component/page] for UI/UX issues.

Check against standards/ui-guidelines.md:
- Design tokens: graphite/cloud/emerald palette (not warm-paper)
- Component library: shadcn/ui new-york style, Lucide icons
- Workspace frame: correct layout type for route
- Typography: Inter (sans), Big Shoulders (display), IBM Plex Mono (mono)
- i18n: all user-facing strings in Vietnamese
- Accessibility: semantic HTML, ARIA labels, keyboard nav, WCAG 2.2 AA
- Mobile: bottom nav, safe-area insets, touch targets ≥ 44px
- Virtualization: react-virtuoso for long lists

Report:
- [BLOCKER] [issue] — [file:line] — [fix]
- [WARNING] [issue] — [file:line] — [fix]
- [SUGGESTION] [issue] — [file:line] — [fix]
```

### Database Migration

```
Create a database migration for: [description of schema change]

Requirements:
- Hand-written Alembic revision (not auto-generated)
- Reversible (provide downgrade path)
- No data loss without explicit documentation
- No long-running locks on production tables

Pattern:
1. Create revision: .venv/bin/alembic revision -m "[description]"
2. Implement upgrade(): [schema change]
3. Implement downgrade(): [reverse schema change]
4. Test locally: alembic upgrade head → alembic downgrade -1 → alembic upgrade head
5. Add the new model to backend/app/models/ (if new table)

Constraints:
- ORM models mirror the schema but do NOT auto-generate migrations.
- Use op.add_column with server_default for non-null columns on existing tables.
- Never drop a column without confirming no code references it.
- See AGENTS.md §13 — migrations require human approval.
```

### Architecture Review

```
Review the architecture of [module/feature/PR] against AGENTS.md §4.

Check:
- Layering: API → Services → Models/Core. No shortcuts.
- Dependency rules: Graph → Ports (Protocols), not concrete classes.
- No circular imports.
- Folder ownership respected (see AGENTS.md §3).
- New code matches existing patterns (read 2-3 neighbors).
- No god files / god modules (see backend/docs/architecture-audit-2026-07-08.md).
- Performance: no N+1, no blocking I/O, virtualized lists.
- Security: auth enforced, input validated, no secrets logged.

Report:
- [VIOLATION] [rule broken] — [file:line] — [remediation]
- [RISK] [concern] — [file:line] — [mitigation]
- [PATTERN] [good pattern found] — [file:line] — [note]
```
