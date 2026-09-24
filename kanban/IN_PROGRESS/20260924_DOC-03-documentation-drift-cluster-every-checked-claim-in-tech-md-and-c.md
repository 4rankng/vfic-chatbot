---
id: DOC-03
title: "Documentation drift cluster — every checked claim in TECH.md and codebase-summary.md except one is wrong"
severity: high
area: docs
labels: [documentation]
effort: M
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# DOC-03 — Documentation drift cluster — every checked claim in TECH.md and codebase-summary.md except one is wrong

**Severity:** high · **Area:** docs · **Effort:** M · **Labels:** documentation

**Trạng thái:** IN_PROGRESS

## Problem

Seventeen facts in the two documents that `AGENTS.md`/`TECH.md` designate as sources of truth are contradicted by the code — the auth library, the migration head, the entity count, the queue set, the service topology and ten line numbers among them. The auth row is actively dangerous: it describes a CVE-bearing library this repo deliberately removed.

## Evidence

- **Auth library.** `TECH.md:29` says "**python-jose** JWT" and `docs/codebase-summary.md:160` says "python-jose HS256 JWT"; `backend/app/core/security.py:23` is `import jwt` (PyJWT), `:10-15` documents the migration ("PyJWT replaced python-jose… python-jose 3.5.0 still pulls `ecdsa` (CVE-2024-23342)"), and `backend/pyproject.toml` declares `pyjwt[crypto]>=2.9.0` with no jose.
- **Migration head.** `TECH.md:21` says "0001–0053, current head `0053_single_page_external_source_sync_state`" and `docs/codebase-summary.md:40` says "migrations through 0050"; `backend/alembic/versions/0054_channel_account_projects.py` is tracked and is the single head — 4 versions behind the code, 2 behind its own sibling doc.
- **Counts and topology.** `TECH.md:79` says "21 entities" against 65 `__tablename__` classes across `backend/app/models/*.py` (3.1× understated); `TECH.md:24` says "**4 queues**" and `TECH.md:143` names a `chat` queue, while `backend/docker-compose.yml:84,116,139,175` consumes five queues (`webhook_high`, `recovery`, `persistence_low`, `ingest`, `followup`) and no `chat` queue exists; `docs/codebase-summary.md:187` says "**10-service** prod stack (… worker-chatbot **×6** …)" while compose defines 13 services with `web-blue` **and** `web-green` and `worker-chatbot: replicas: 3` (`backend/docker-compose.yml:87`).
- **Ten stale line numbers** in `docs/codebase-summary.md:163-173`: `BotRunState`/`GraphDeps` cited at `:163` are at `backend/app/graph/types.py:37`/`:118`; `build_deps` at `:164` is at `backend/app/graph/factories.py:760`; `GeminiEmbedder` at `:165` is at `backend/app/graph/clients.py:531`; the Zalo senders at `:170-172` are at `backend/app/services/zalo_sender.py:22`, `zalo_bot_service.py:347`, `zalo_oa_service.py:64` (endpoint at `:289/:360/:367/:415`); retrieval "(line 160)" at `:173` is `backend/app/services/retrieval/repository.py:34`/`:222`.
- **Library, README, remote and paths.** `TECH.md:41` says virtualization is "**react-virtuoso** `^4.18` — all long lists" while `frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:14` is `import { VList } from "virtua"` (virtuoso survives only in `dashboard/RecruitingCommandCenter.tsx:5`); `docs/codebase-summary.md:85` claims a root `README.md` that does not exist; `:3` names remote `git@github.com:4rankng/ChatBotN8N.git` against `.git/config`'s `vfic-chatbot.git`; `:208`/`:75` give the wrong `inbox.css` path and 10 vs 19 CSS files. `docs/codebase-summary.md:100-101`'s LOC table is **[UNVERIFIED]** — no `cloc` was available, and measured file-size anchors suggest the per-area figures are low.

## Impact

~17 wrong facts mislead capacity reasoning on the 2 vCPU box (entity, queue and service counts), send readers to unrelated code (ten line-number claims), and one row describes `python-jose` — the library this repo deliberately migrated away from because of CVE-2024-23342.

## Suggested fix

Treat `docs/codebase-summary.md` as a generated artifact: regenerate it from the tree (or delete it and keep only `TECH.md` plus `docs/system-architecture.md`); make the key-files table symbol-based ("`BotRunState` in `app/graph/types.py`") rather than line-based; run one `cloc` pass and replace the LOC table; and add the two fastest-drifting facts (migration head, entity count) to a CI check.

## Notes

Merge with OPS-12 (operator-critical knobs, same drift class) and DOC-11 (staleness); the missing root `README.md` row is also DOC-10.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
