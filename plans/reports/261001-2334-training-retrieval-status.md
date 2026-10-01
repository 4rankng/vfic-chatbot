# Training, retrieval, native status, and category migration handoff

## Scope and artifacts

Implement robust one-file project training, current scoped KB retrieval, native Zalo Bot status every three seconds, and an admin migration action for existing projects to twelve categories. Preserve prior authorized work. Deliver `plans/exports/2026-10-01-training-retrieval-status.patch` cumulatively from main `35d970689cbb092e4f9100f1e60305c9bd7505ed`, plus an incremental patch after `2026-10-01-architecture-hardening.patch`.

No branch, commit, push, PR, deployment, production data change, or real candidate message was performed. Existing unrelated work and the real Git index are preserved. Exports use a private index and are checked against a clean archive for bytes, executable modes, and reverse application.

## Changes and causes

- Plain Vietnamese briefs previously missed headings, FAQ groups, job descriptions, decimal income, contact hours, insurance prose, and transport pickup times. Extraction now preserves these facts across the twelve supported category contracts. Explicitly absent shuttles cannot generate fictional routes. Conflicting, qualified, missing, unsupported or oversized facts remain available for review rather than acquiring invented values.
- Typed Category Markdown bundles retain their fields. Blank commented templates stay empty. Unknown/duplicate categories and malformed duplicate sections are rejected instead of being silently truncated. The actual rich frontend-generated twelve-category plan passed backend validation and rendering.
- Empty and ungrounded digests retry, then preserve verbatim source units. Unicode/whitespace-equivalent source quotes are accepted. Uncovered source tails and omitted facts remain searchable without increasing model-call budgets, and full bounded fallback quotes reach the actual chatbot evidence renderer.
- Original-file extraction and storage run off the async event loop. Version ingestion rolls back failed SQL before saving a safe retry receipt. A live PostgreSQL regression proves retained-source retry; configuration/provider errors do not leak private error bodies into receipts or logs. Shared batch embedding contracts and repository return types now pass typing without weakening checks.
- Explicit empty retrieval scopes fail closed; Page scopes are intersected with the current active project catalog. Retrieval verifies KB attachment, category revision/document ownership, and denormalized chunk ownership. Both exact and ANN paths exercise all twelve categories. Citations identify the current project/category/source. Oversized hits cannot starve all later ranked evidence, and degraded reads cannot poison negative evidence caches.
- Native Zalo Bot status starts during worker setup, continues through initial runtime/ownership checks, and uses absolute three-second deadlines with bounded non-overlapping provider requests. Transient failures retry; worker handoff, answer delivery, terminal outcomes, errors and cancellation drain status tasks. Unsupported OA/Messenger paths produce no filler messages. The orphan ingress task and raw chat ID failure logs are removed. Contract: https://bot.zapps.me/docs/apis/sendChatAction/ .
- Legacy RAG projects now expose the existing twelve-category migration action through server-owned `category_authority_started` state. Migration retains written/active/cleared categories, rejects pending processing, and clears only unwritten empty categories. Individual, batch and clear projections share a policy that preserves published legacy/single-page knowledge until cutover. Cutover rejects missing/misowned KBs and wrong-owner or non-ACTIVE revision pointers; rollback behavior is preserved.

## Verification

- Training: 111 frontend domain tests, 98 focused backend tests, and 51 PostgreSQL ingestion/training tests passed.
- Retrieval: 116 focused tests and 14 PostgreSQL tests passed; exact and ANN current/superseded/inactive/cross-Page/ownership cases exercised.
- Native status: 262 tests passed, including architecture boundaries, controlled 0/3/6-second cadence, bounded credential/provider waits, unsupported providers, and lifecycle cleanup.
- Version failure recovery: three PostgreSQL tests passed, including aborted-transaction receipt/retry and provider-error privacy.
- Migration: 88 backend unit tests, 11 PostgreSQL tests, and all 33 project panel tests passed. The initial new UI selector failure was corrected without changing production behavior. The earlier full frontend run had 912 passing tests and one obsolete twelve-category assertion for a no-shuttle brief; the complete panel rerun verifies the corrected eleven-category result plus review state.
- Backend typing over graph, knowledge/retrieval services, ingestion, embedding/config and workers: zero errors/warnings. Frontend typing and scoped migration lint/formatting passed. Whole backend Ruff passed; whole frontend ESLint had zero errors and 35 existing generated/vendor warnings.
- Production build passed. Built-bundle smoke renders login without page errors. Registry validation covers 232 paths. Agent routing validates 32 paths and four targets. Offline golden release gate: 100 percent pass; production latency SLO was not evaluated.
- Runtime inventory remains unchanged: 10 outbox, 91 provider and 42 queue boundaries; the reviewed hash is unchanged. No new transport endpoint, queue or outbox producer was added.

## Explicit handoff limits

The user explicitly requested immediate wrap-up and the full patch. The broad backend run was stopped after 2,336 passed / 30 skipped / two existing warnings, without a completed full-suite result. The late migration changes have focused unit, PostgreSQL, UI and typing evidence; the entire final frontend/backend suites were not rerun after those changes. The completion checklist therefore marks the broad-regression gate BLOCKED, and this handoff is not a production-release certification.

No live model extraction, live Zalo delivery, deployment or production migration was exercised. Missing facts still need administrative review. Cutover validates active revision identity/status and relies on the existing activation validators; an additional independent indexed-evidence completeness audit was not added during wrap-up.

Only the task-owned local PostgreSQL container was removed after test cleanup; unrelated local services remain intact.
