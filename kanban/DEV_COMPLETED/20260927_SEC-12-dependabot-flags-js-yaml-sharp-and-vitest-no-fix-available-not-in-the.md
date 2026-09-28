---
id: SEC-12
title: "Dependabot flags js-yaml, sharp and vitest with no fix available; none reach the production bundle"
severity: low
area: security
labels: [dependencies, security, supply-chain]
effort: S
status: todo
column: TODO
opened: 2026-09-27
---

# SEC-12 — Dependabot flags js-yaml, sharp and vitest with no fix available; none reach the production bundle

**Severity:** low · **Area:** security · **Labels:** dependencies, security, supply-chain

**Trạng thái:** TODO — assessed 2026-09-27 before the 2026-09-27 production deploy; deliberately not treated as a deploy blocker

## Problem

GitHub's push to `main` reports: *"GitHub found 3 vulnerabilities on 4rankng/vfic-chatbot's default branch (2 high, 1 moderate)."* The alerts are for `js-yaml`, `sharp`, `vitest`, `@vitest/mocker` and `baseline-browser-mapping`. Nothing has been fixed, so the count will keep appearing on every push until someone either upgrades or the advisories are dismissed.

## Evidence

Alerts, from `gh api /repos/4rankng/vfic-chatbot/dependabot/alerts`:

- **high** `npm/js-yaml` — "maxTotalMergeKeys does not limit CPU use for empty merge sources" (reported twice, two dependency paths)
- **high** `npm/sharp` — libheif `GHSA-g89c-p67h-r497`, `GHSA-2jg2-4ch7-h545`; and inherited libvips `CVE-2026-33327`, `CVE-2026-33328`, `CVE-2026-35590`, `CVE-2026-35591`
- **medium** `npm/vitest` and `npm/@vitest/mocker` — path traversal / arbitrary file read via `@vitest/mocker` redirect mock
- **medium** `npm/baseline-browser-mapping` — process termination on invalid input causes denial of service

Reachability, checked 2026-09-27 against the tree and the real build output:

- `js-yaml` is **transitive and dev-only**. `npm ls js-yaml` shows exactly two parents: `eslint@9.34.0 → @eslint/eslintrc → js-yaml@4.3.2` and `shadcn@3.5.0 → cosmiconfig → js-yaml@4.3.2`. Neither ships.
- `sharp` is **not a frontend dependency at all** — it does not appear in `npm ls` for this project, and no `dist/assets/*.js` chunk references it or `libvips`. The alert is almost certainly for a different ecosystem path in the repository (the Python backend) or a stale default-branch scan.
- `vitest`, `@vitest/mocker` and `baseline-browser-mapping` are **test tooling**. None appears in `dist/`.
- No `js-yaml`, `sharp` or `libvips` string appears in any production chunk under `frontend/dist/assets/`.

Fix availability, from `npm audit`: **none of these have a fix available.** The local audit reports a different and lower-severity set entirely (`moderate`: `decode-uri-component`, `query-string`, `ra-core`, `ra-i18n-polyglot`), which suggests the GitHub alerts are computed against a different resolution than the committed lockfile.

## Impact

**None in production, as the code stands.** The two high-severity advisories are in a linter and a scaffolding CLI that never run in a deployed container, and in a package this project does not depend on. The medium ones are in the test runner.

The real cost is the signal: an alert banner on every push trains everyone to ignore the dependency scanner. The next genuine high-severity finding will be scrolled past with the same reflex.

## Suggested fix

1. **Do not upgrade to chase these.** Every one has no fix available, so a version bump buys nothing and risks a lockfile change with no security benefit immediately before a release. The correct time to move `vitest` is the next routine dependency refresh, not in response to a dev-tooling path-traversal advisory.

2. **Re-run the audit against the lockfile** and reconcile it with GitHub's list. If the two disagree, the GitHub alerts are computed against a resolution this repo does not use; dismissing them with that evidence is correct, and dismissing them without it is not.

3. **Make the scanner mean something again.** The cheapest real fix: wire `npm audit --audit-level=high` into `release-check` so the gate fails on a *new* high-severity finding in a package that actually ships, and record the known dev-tooling exclusions in one place with this reasoning attached. Right now nothing scans automatically — `TEST-06` covers that gap and this card is the reason to close it.

4. **Re-examine when a boundary moves.** The exclusions in this card are valid only while the affected packages stay dev-only. If `js-yaml` or `sharp` ever enters `dependencies` rather than `devDependencies`, this card's reasoning no longer holds and the advisories become real.

## Notes

Assessed 2026-09-27 immediately before deploying the kanban sweep to production. Recorded rather than silently dismissed, so the next person who sees the banner has the analysis instead of starting over.
