# SEC-12 audit gate wired; DOC-19 redirect held — premise stale, constitution already restored

## Outcome

**SEC-12 (Task A): DONE.** `npm audit --omit=dev --audit-level=high` is wired
into the root `Makefile` `release-check` (verified exit 0 before wiring), and
the dev-tooling exclusions + boundary condition are recorded in
`docs/ops/deployment-guide.md` §3 ("Dependency audit gate"). No package.json or
lockfile touched, no upgrades, no new script entries.

**DOC-19 (Task B): HELD — not executed, awaiting lead confirmation.** The task's
premise (constitution deleted, redirect only) no longer matches the tree: the
owner restored AGENTS.md and standards/ in commit `d92c1584` (2026-09-27 18:56,
git user 4rankng, "docs: restore the repository constitution and gate its
routing"), which also created `scripts/check-doc-links.mjs` and wired it into
`release-check`. `6064082d` (09-28 11:35) then removed the
`check-agent-rules-committed.mjs` gate-into-`.claude` lane. At HEAD everything
Task B wanted to fix already resolves; executing the redirect would reverse the
owner's committed restore decision. Evidence sent to the lead; no edits made to
`.claude/CLAUDE.md`, `check-doc-links.mjs`, or the Makefile's routing message.

## Task A — evidence and reconciliation

### Local audit vs GitHub alerts (frontend/, lockfile-resolution, 2026-09-28)

| Package (GitHub alert) | GitHub severity | In local `npm audit`? | Local status |
|---|---|---|---|
| js-yaml | high | no | dev-only transitive: `eslint@9.34.0 → @eslint/eslintrc → js-yaml@4.3.2` and `shadcn@3.5.0 → cosmiconfig → js-yaml@4.3.2` (`npm ls`) |
| sharp | high | no | absent from `npm ls` entirely — not a frontend dependency |
| vitest / @vitest/mocker | medium | no | dev-only test tooling (`vitest@4.1.11` under @vitest/* and vitest-browser-react) |
| baseline-browser-mapping | medium | no | dev-only via `shadcn → browserslist → baseline-browser-mapping@2.11.23` |
| (not alerted by GitHub) | — | decode-uri-component, query-string, ra-core, ra-i18n-polyglot | 4 × moderate, production `ra-core` chain, no fix available |

Full audit and production-only audit both report exactly these 4 moderates —
0 high, 0 critical. Reconciles with the card's conclusion: GitHub's banner is
computed against a different resolution than the committed lockfile. The
lockfile audit is what the gate trusts.

### The gate (exact Makefile step added)

Placed in `release-check` after the doc-links check, before the test lanes
(fail fast):

```make
	# Dependency audit: fails the release on a new high/critical advisory in a
	# package that actually ships. Dev-only tooling is deliberately out of
	# scope — exclusions and boundary condition: docs/ops/deployment-guide.md §3.
	@cd frontend && npm audit --omit=dev --audit-level=high
```

Matches the card's rule: `--omit=dev` keeps test tooling out of scope (a
dev-only finding can never fail the gate), `--audit-level=high` fails on new
high/critical in shipping packages. Verified standalone before wiring:

```
cd frontend && npm audit --omit=dev --audit-level=high
AUDIT_EXIT_RAW=0   (4 moderate findings reported, all below threshold)
```

Notes: requires registry access (fails closed if the audit endpoint is
unreachable — release-check was previously offline); no `.github/workflows/`
exists, so there is no TEST-06 CI scan lane to align with — the Makefile itself
documents "there is no CI in the loop", so the Makefile gate is the whole
story. No package.json/lockfile churn.

### Docs record

`docs/ops/deployment-guide.md` §3, new subsection "Dependency audit gate
(`npm audit`)" (18 lines, inserted between "Full deploy" and "Blue/green
cutover"): what the gate runs, fail-closed behavior, the three exclusion
groups with why, the boundary condition (exclusions valid only while the
packages stay out of `dependencies`), the standing ra-chain moderates, and the
GitHub-vs-lockfile resolution mismatch. One page, existing owning surface —
no new file.

## Task B — why it was held (evidence for the lead)

1. `d92c1584` (09-27 18:56, owner) restored AGENTS.md + standards/ reconciled
   against the current tree; same commit added `check-doc-links.mjs` and wired
   it into `release-check`. `6064082d` (09-28) removed the `.claude` routing
   lane.
2. At HEAD: `node scripts/check-doc-links.mjs` → exit 0, "55 paths and 4 make
   targets across 4 documents all resolve". The 4 scanned documents
   (AGENTS.md, standards/agent-completion-checklist.md,
   standards/definition-of-done.md, standards/review-checklist.md) are all
   git-tracked (`git ls-files` lists all four) and all exist. Nothing dead to
   re-point.
3. `.claude/CLAUDE.md`'s hand-written section routes only to files that exist
   post-restore; zero dead references. Its "AGENTS.md is the binding contract"
   claim is factually true again.
4. `git ls-files .claude/CLAUDE.md` returns nothing — it is untracked, so per
   the script's own header rule it must NOT join SCANNED_DOCUMENTS (exactly
   what `6064082d` deliberately unwired).
5. Executing Task B would strip valid routing and shrink gate coverage —
   reversing the owner's committed decision. The memory note about the
   deliberate deletion predates the restore. Suggested: close DOC-19 as
   resolved-by-restore (I have not touched any kanban card).

## Verification

- `cd frontend && npm audit --omit=dev --audit-level=high` → exit 0 (standalone, before and after wiring).
- `make -n release-check` → parses; recipe shows doc-links check then the new audit line.
- `node scripts/check-doc-links.mjs` → exit 0 (55 paths / 4 make targets / 4 documents).
- `git diff --stat` (my changes): `Makefile +4`, `docs/ops/deployment-guide.md +18`. The `backend/app/services/lead/repository.py` modification in the shared tree belongs to a parallel teammate (likely ops29-lead-types); I never touched it. No `.claude/CLAUDE.md` or `scripts/` changes made.

## Unresolved

- ~~Lead decision on DOC-19 / Task B~~ — RESOLVED 2026-09-28: the lead confirmed
  my analysis, dropped Task B, and approved Task A as executed. The lead owns
  the DOC-19 card disposition at integration (resolved-as-restored,
  `d92c1584` + `6064082d` as evidence).

## AGENTS.md influence on Task A (per lead's request)

The restored constitution (AGENTS.md, read in full after the lead's
confirmation) affected Task A in four concrete ways:

1. **Dependency-approval gate never triggered.** "Adding, removing, or
   upgrading dependencies" requires approval — the audit gate only *reads*
   dependency state; package.json/lockfiles are untouched, so no dependency
   change was ever proposed.
2. **Root `Makefile` is an AGENTS.md protected path.** The edit is the kanban
   card's own suggested fix #3, assigned verbatim by the lead, and is additive
   (one gated step; every existing gate untouched) — approval carried by the
   task assignment itself.
3. **Docs conventions.** AGENTS.md step 6 permits docs updates for changes to
   commands or security posture — exactly what this is — and its task routing
   names `docs/ops/deployment-guide.md` as the deployment source, so the
   exclusions record landed there rather than in a new file.
4. **Completion contract reinstated.** Step 5 (copy
   `standards/agent-completion-checklist.md` and fill every gate) applies
   again now that standards/ is restored: the filled 16-gate record is at
   `plans/reports/260928-1844-sec12-audit-gate-completion.md`.

Additionally, AGENTS.md step 4's rule (run `node scripts/check-doc-links.mjs`
when routing changes) was satisfied — routing did not change and the gate exits 0.
- SEC-12 remains open on the kanban for the owner: the GitHub alert banner itself can only be cleared by dismissing/fixing on GitHub's side; this task wired the local gate + recorded the exclusions, per the card's own suggested fix.

Docs impact: minor — the release gate gained one step whose exclusions and boundary condition needed a durable home; recorded in the existing owning surface, docs/ops/deployment-guide.md §3.

Status: DONE_WITH_CONCERNS
Summary: SEC-12 done — audit gate wired into release-check (verified exit 0) with exclusions recorded in deployment-guide §3; DOC-19 held because the owner already restored the constitution and gate in d92c1584, making the redirect instructions destructive if executed.
Concerns/Blockers: Task B needs the lead's decision; the DOC-19 TODO card is stale relative to d92c1584.
