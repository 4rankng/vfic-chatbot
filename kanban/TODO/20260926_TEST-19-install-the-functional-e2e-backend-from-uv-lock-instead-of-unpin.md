---
id: TEST-19
title: "Install the functional-e2e backend from uv.lock instead of unpinned pip -e .[dev]"
severity: low
area: testing
labels: [ci, dependencies, reproducibility]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# TEST-19 — Install the functional-e2e backend from uv.lock instead of unpinned pip -e .[dev]

**Severity:** low · **Area:** testing · **Effort:** S · **Labels:** ci, dependencies, reproducibility

**Trạng thái:** TODO

## Problem

functional-e2e is the only backend job that ignores the lockfile: it creates a venv, upgrades pip unpinned, and installs -e .[dev] with fresh resolution, while backend-unit, backend-integration, release-gate, and dependency-audit all install via `uv sync --all-extras --frozen`. The two highest-blast-radius journeys therefore execute against dependency versions nothing else in CI (and not the shipped image) has verified.

## Evidence

- .github/workflows/quality-gates.yml:49-50,115-116,336-337,411-412 — backend-unit, backend-integration, release-gate, dependency-audit all run `uv sync --all-extras --frozen`
- .github/workflows/quality-gates.yml:219-222 — functional-e2e instead runs `pip install --upgrade pip` (unpinned) and `pip install -e .[dev]`, resolving fresh from pyproject ranges
- backend/pyproject.toml:9-10 — 'Exact versions come from uv.lock: the image and CI install from it' — which the e2e job's install method contradicts

## Impact

A transitive bump that only resolves under pip's looser resolution can break the e2e journeys (or silently change behavior under test) while the locked lanes stay green — the two lanes can disagree about which code passed. Fresh resolution also makes e2e the least reproducible job on every run.

## Suggested fix

Replace the venv+pip steps with the same astral-sh/setup-uv@v5 + `uv sync --all-extras --frozen` pair the other jobs use (the pip cache line can go). If the e2e job intentionally wants a lighter install, use `uv sync --frozen --no-dev` plus the playwright extra rather than a fresh pip resolve. CI files are approval-gated.

## Notes

Dependabot pip-vs-uv.lock is a known watch item and unchanged — this card is the CI job, not the dependabot config.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
