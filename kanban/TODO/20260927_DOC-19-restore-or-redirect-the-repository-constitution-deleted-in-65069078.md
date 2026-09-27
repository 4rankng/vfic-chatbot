---
id: DOC-19
title: "The repository constitution and standards/ are deleted, but .claude/CLAUDE.md still routes agents to them"
severity: high
area: docs
labels: [documentation, agent-context, governance]
effort: S
status: todo
column: TODO
opened: 2026-09-27
---

# DOC-19 — The repository constitution and standards/ are deleted, but .claude/CLAUDE.md still routes agents to them

**Severity:** high · **Area:** docs · **Labels:** documentation, agent-context, governance

**Trạng thái:** TODO — found 2026-09-27 by the sweep report writer; not fixed by that sweep

## Problem

`AGENTS.md` and the entire `standards/` directory were deleted in commit `65069078` ("Refactor codebase: Remove unused types, delete outdated standards documents, and streamline performance guidelines"). The file that every coding agent loads first still routes to all of them. An agent following the instructions gets sent to four documents that no longer exist.

This is not cosmetic. `AGENTS.md` was the binding contract: where business logic belongs, which paths are approval-gated, that secrets are never edited, that agents do not commit unasked. With it gone, the repo has no stated architecture rule, no approval list, and no completion checklist — the things AGENTS.md existed to hold in place.

## Evidence

Verified 2026-09-27 at HEAD, all four absent:

- `AGENTS.md` — MISSING (deleted in `65069078`)
- `standards/agent-completion-checklist.md` — MISSING
- `standards/definition-of-done.md` — MISSING
- `standards/review-checklist.md` — MISSING

The surviving routing file is `.claude/CLAUDE.md`, which is loaded into every agent's context as the repo's binding rules. It still contains, among others:

- a "Sources of truth" list naming `standards/agent-completion-checklist.md` as the completion record
- a task-routing table whose entries point at the deleted skill and doc paths
- the scoped workflow's step 5, which requires copying `standards/agent-completion-checklist.md` to `plans/reports/` and filling every gate — a file that no longer exists, so step 5 cannot be followed

Concrete downstream evidence: the completion report written at the end of the 2026-09-27 sweep (`plans/reports/260927-kanban-sweep-completion.md`) had to **reconstruct** the 16-gate checklist from the previous sweep's report, because the checklist itself was gone. The author of that report noted the reconstruction in the report. That is the failure mode in miniature: the gate list now lives only in whatever report happened to be written most recently.

## Impact

- **No stated approval gate.** AGENTS.md's "Approval required" list — migrations, webhooks, auth, bot prompts/safety, dependency changes, deployment files — is gone. Nothing in the repo now tells an agent to stop and ask before touching those. The owner granted blanket approval for the 2026-09-27 sweep, but that was a one-off decision, not a durable rule, and it is now the only record that those paths are sensitive.
- **No completion contract.** "Fill every gate with PASS/N/A/BLOCKED plus evidence" has no checklist to fill. Reports degrade toward whatever the author remembers.
- **Silent instruction drift.** Nothing fails when a routing target disappears. There is no link check, no docs-drift gate over `.claude/CLAUDE.md` — the release gate's docs-drift step greps only `docs/ops/deployment-guide.md` for the Alembic head.
- **Knowledge loss may be partial.** `65069078` says "delete outdated standards documents", which suggests the content was believed stale. Whether anything of value was lost is unverified — the prior contents are recoverable from `git show 65069078^:AGENTS.md` and are worth reading before deciding to restore rather than rewrite.

## Suggested fix

Decide restore-versus-rewrite first, and do not skip that decision — it changes everything else.

1. **Recover and diff.** `git show 65069078^:AGENTS.md` and the same for each deleted `standards/` file. Classify what was genuinely stale (counts, dead doc names) versus what was still load-bearing (the boundary rules, the approval list, the completion gates). The sweep's own card history shows several of these documents were *recently corrected* — DOC-14 through DOC-18 fixed stale claims in exactly these files days before they were deleted.

2. **Then either:**
   - **restore** the constitution, applying only the corrections the sweep already made to the doc-drift cards, and re-point `.claude/CLAUDE.md` at the restored paths; or
   - **rewrite** it, if the layered `domain/application/presentation` structure and the current toolchain genuinely supersede the old rules — in which case the new file must still carry the four things nothing else holds: architecture boundaries, the approval-gated path list, the secrets rule, and the completion contract.

3. **Add a link check** so this cannot recur silently: assert that every path named in `.claude/CLAUDE.md` exists, and fail the release gate when one does not. This is the same class as the Alembic docs-drift gate that *did* catch a real drift during this sweep, and the repo already has that pattern to copy.

## Notes

- Found while writing the 2026-09-27 sweep completion report; the report records the checklist reconstruction it was forced into.
- No fix attempted by that sweep. Restoring or rewriting the repo's constitution is an owner decision about how this project is governed, not a documentation edit.
- Related: the sweep also had to record its own gate breakage in a new card when migration `0057` left `docs/ops/deployment-guide.md`'s CI-guarded Alembic head stale. The fix was one line. This card is the same failure class at a larger scale, and it is why step 3 matters more than steps 1 and 2.

---

_Opened 2026-09-27 from the completion-report pass of the kanban sweep. Every path above was checked on the live tree; the prior contents are recoverable from commit `65069078^`._
