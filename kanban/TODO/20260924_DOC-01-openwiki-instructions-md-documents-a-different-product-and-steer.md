---
id: DOC-01
title: "openwiki/INSTRUCTIONS.md documents a different product and steers the wiki agents are told to consult"
severity: critical
area: docs
labels: [documentation, tech-debt]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# DOC-01 — openwiki/INSTRUCTIONS.md documents a different product and steers the wiki agents are told to consult

**Severity:** critical · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt

**Trạng thái:** TODO

## Problem

`openwiki/INSTRUCTIONS.md` describes TingTing as a Vietnamese trucking-logistics platform built as a TypeScript monorepo with Express v5, Drizzle ORM, Casbin RBAC and a `shared/` package — none of which exist here. `AGENTS.md` tells agents to treat the generated `openwiki/` index as an evidence source, and a tracked CI workflow regenerates it weekly from that brief, so the wiki is generated against a fictional architecture.

## Evidence

- `openwiki/INSTRUCTIONS.md:11-13` — "TingTing … is a Vietnamese **trucking logistics platform** for managing trips, drivers, customers, fleet vehicles, and financials"; `:14-24` claims "a TypeScript monorepo with three packages", "`backend/` — Express v5 + TypeScript API on port 3090; **Drizzle ORM**… **Casbin RBAC**", "`frontend/` — React **18**" and "`shared/`".
- `backend/pyproject.toml:2` is FastAPI, and `.git/index` shows `backend/app/**` is Python with no `shared/` directory anywhere.
- `openwiki/INSTRUCTIONS.md:26-32` invents roles (`ACCOUNTANT`, `DRIVER`), a trip lifecycle (`PENDING → IN_PROGRESS → COMPLETED → SETTLED`) and VND money math; `:39-46` points at `docs/flows/DELIVERY_TRIP_LIFECYCLE.md`, `docs/company-files/`, `TASKS.md` and `shared/src/calculations/` — none of which exist in this repo.
- `AGENTS.md:88-92` — "This repository has a generated `openwiki/` evidence index… Treat source code and tests as authoritative"; `.github/workflows/openwiki-update.yml` is tracked, so CI regenerates the wiki weekly from the wrong brief.
- Staleness compounds it: `openwiki/.last-update.json` records `updatedAt 2026-09-21T12:39:13Z` with `status: "interrupted"`, while `openwiki/.page-manifest.json:1-33` stamps every page with a different `gitHead` (`10de99a…`) than either the run file or current HEAD `923b1d3`.

## Impact

The AI evidence index is generated against a fictional architecture, so any agent that follows `AGENTS.md` into `openwiki/` gets confidently wrong guidance about stack, layering and domain — and the weekly CI job keeps regenerating it, so the wrongness is self-renewing. It also explains why the pages are low-value.

## Suggested fix

Rewrite `openwiki/INSTRUCTIONS.md` from `TECH.md` plus `docs/system-architecture.md`, or delete `openwiki/` entirely and remove `.github/workflows/openwiki-update.yml` and the `AGENTS.md:88-92` OpenWiki block. Do not hand-edit page files. Also remove the `.claude/skills/**` and `.claude/hooks/**` re-includes from `.openwikiignore:20-25` so generation is driven by product source rather than 1,801 vendor skill files.

## Notes

Hygiene finding F11 (openwiki staleness) is covered here. If the brief is not fixed first, deleting `openwiki/` is the cheaper option.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
