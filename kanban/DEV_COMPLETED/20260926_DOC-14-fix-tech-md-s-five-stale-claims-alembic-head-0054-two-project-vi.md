---
id: DOC-14
title: "Fix TECH.md's five stale claims: Alembic head 0054, two-project Vitest, RetrievalPort, dead GraphDeps.safety seam"
severity: medium
area: docs
labels: [documentation, tech-debt, agent-context]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-26
---

# DOC-14 — Fix TECH.md's five stale claims: Alembic head 0054, two-project Vitest, RetrievalPort, dead GraphDeps.safety seam

**Severity:** medium · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt, agent-context

**Trạng thái:** DEV_COMPLETED

## Problem

The post-sweep commits (migration 0055, the safety-layer removal/think-strip rename, the GraphRetrievalPort seam typing, the vitest claude-project removal) landed after TECH.md was last aligned, and five of its normative claims no longer match the tree. Because CI's docs-drift guard only checks deployment-guide.md's Alembic head, TECH.md rots silently.

## Evidence

- TECH.md:21 — 'hand-written (0001–0054, current head `0054_channel_account_projects`)'; backend/alembic/versions/0055_memories_match_halfvec.py:36-37 declares revision 0055 revising 0054
- TECH.md:52 — 'Tests — Vitest 4 (two projects: `app` Playwright browser, `claude` Node)'; frontend/vitest.config.ts:9 says 'One test project' and package.json:5-11 defines no test:unit:claude
- TECH.md:87-88 — graph layer 'depends on Protocol interfaces (ConversationPort, RetrievalPort, LeadContextPort, FaqBypassPort)'; ports.py defines no RetrievalPort — the protocol is GraphRetrievalPort (ports.py:218, exported :265), plus TurnDecisionsPort (:62), RuntimePolicyPort (:208), DirectContextPort (:250)
- TECH.md:105-106 — '`GraphDeps.safety` is an unwired seam… (`MiniMaxSafety` has no call site)'; repo-wide grep finds zero hits and GraphDeps (graph/types.py:122-134) has no safety field — removed by 38ad9d6a
- .github/workflows/quality-gates.yml (backend-unit 'Docs drift check') — the CI guard greps only ../docs/deployment-guide.md for the current alembic head; TECH.md's head claim has no guard

## Impact

TECH.md is AGENTS.md's declared 'system map and stack' source of truth that agents load first. An agent writing migration 0056 from TECH.md:21 sets down_revision=0054 and creates an Alembic multiple-heads break. The phantom safety seam and wrong port names send readers hunting for symbols that no longer exist, and the vitest claim breaks `npm run test:unit:claude` for anyone who runs the documented command.

## Suggested fix

Five one-line edits in TECH.md: :21 → head 0055_memories_match_halfvec; :52 → one Vitest project; :87-88 → the real seam set (ConversationPort, GraphRetrievalPort, LeadContextPort, FaqBypassPort, TurnDecisionsPort, RuntimePolicyPort); :105-107 → replace the safety-seam paragraph with the current statement that the only user-visible reply transform is graph/think_strip.py:strip_think_reasoning. Then harden CI: extend the docs-drift step to grep TECH.md's head marker too, or drop the revision id from TECH.md and link deployment-guide.md:242 as the single guarded source.

## Notes

Port-name drift also live in docs/testing.md:44 and standards/coding-style.md:22 (DOC-15/DOC-17); migration head is correct in docs/deployment-guide.md:242 (CI-guarded).

## Evidence log

- TECH.md Alembic head corrected to 0056 — the audit's 0055 was superseded by 0056_project_external_api after the audit; matches CI-guarded deployment-guide.md:245.
- The CI-hardening half self-resolved: quality-gates.yml was deleted in e7010b22 (gates moved to `make release-check`) and testing.md's CI table was already rewritten by that commit — verified accurate against Makefile:35-56 rather than re-edited. The optional TECH.md-head drift guard in Makefile is deferred to the ops lane.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
