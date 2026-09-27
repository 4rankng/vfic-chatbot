# Investigation — ZaloIntegrationPage.tsx code health (5.5/10)

Date: 2026-09-27 · Trigger: Repowise health report (10 open findings, −4.47) pasted by
the user · Method: two Explore agents (code structure, git archaeology) + ai-slop-cleaner
classification · Outcome: 5.5/10 measured a file that no longer exists; one real defect
(the name) fixed by rename to `SettingsConsolePage`.

## What the findings actually measure

The 2,071-line settings god-file was split on 2026-09-24 (commit `decb8b63`, +66/−2040)
into today's 101-line console shell plus `integrations/presentation/` and
`integrations/application/` modules. Every process-history finding is dominated by that
event and by three wholesale redesigns of the old file (07-02 birth at 253 lines → peak
2,071 at `1ddfa99c` on 09-22), measured by `git log --follow` against the small survivor.

- **dry_violation (46%, 10-line clone with PersonaAssignments.tsx,
  `finding_f904229e7cf70f966b62`) is stale.** Mechanical LCS on the current bytes finds
  4 shared lines (closing braces). The likeliest historical clone was the pending-spinner
  button ternary; it appears zero times in `integrations/` since the split, which instead
  extracted shared primitives (`SettingsChrome`, `SettingsGroup`, `SettingsFieldStatus`,
  `SecretField`). Do not chase this ghost.
- **churn_risk 123.9× / change_entropy top-0.7% / prior_defects 6**: all pre-split
  history. Post-split edits are surgical (+4/−1, +7/−6, +1/−13). The six fixes were one
  regression class — descriptor-panel form reset/save semantics and client/backend
  settings-schema drift (`923b1d3f` reset blanked saved text values; `e0cd975f` removed a
  field obsoleted by the server-side resolver), plus a probe `/v1` edge case and layout
  CSS. No data-loss or security defects, and the paired tests guard exactly the recurring
  class: `SettingsConsolePage.navigation.test.tsx` (25 tests across the 7 sections) and
  the payload test for `buildZaloUpdatePayload`.
- **co_change_scatter (169 files) / hidden_coupling ×3**: genuine but narrow vertical
  contract coupling — `backend/app/schemas/integrations.py` ↔ `integrations/api.ts` ↔
  page, i.e. "add a provider field = touch all three". The 169 figure is inflated by
  three large multi-lane commits (`273a2e49` 60 files, `decb8b63` 25, `e0cd975f` 23).
  This is by-design feature-column co-change, not shotgun surgery.
- **large_method (68 lines, CCN 5)**: the shell is one section-dispatch switch;
  maintainability is already 8.5. Left open deliberately — splitting it is cosmetic.
- **ungoverned_hotspot**: now governed — `plans/260921-2227-settings-provider-panel/`
  is the architectural decision behind the descriptor panel and split; backend twin in
  `plans/reports/sweep-integrations-260924-2024-integration-files.md`.

## The one real defect: the name

The "Zalo" page was the entire `settings` resource — 7 sections (Zalo, LLM providers,
Jev, Tingting, Agents, Users, Messenger) — so unrelated-lane commits (bot, LLM,
Tingting) kept being attributed to a "Zalo" file, poisoning its process signals.

**Fix applied (2026-09-27):** renamed to `SettingsConsolePage.tsx` (symbol and file;
first collision-free name candidate — `SettingsPage` was rejected because
`atomic-crm/settings/` holds profile pages). Dependents updated: `integrations/index.tsx`
lazy import, `settings.css.test.ts` `?raw` import, navigation test (file renamed, 15 JSX
sites, screenshots dir moved — untracked/gitignored), `frontend/registry.json`
regenerated for the `registry:check` CI contract. `ZaloIntegrationPage.test.ts` was left
untouched: it imports only `buildZaloUpdatePayload` and never referenced the page file;
its filename is a residual minor misnomer.

Verification: `npm run typecheck`, `npm run lint`, targeted vitest (3 files, 25/25) —
all pass. No CSS class strings changed.

## Repowise bookkeeping

The health engine stores per-file analysis (`get_health` still returned nloc 90 and the
46% clone after the split) and refreshes only via `repowise update` after the relevant
changes are committed; there is no local CLI verb for marking finding states. Recorded a
`repowise decision add` entry (lands `proposed`) stating that
`finding_f904229e7cf70f966b62` is a false positive post-`decb8b63` and the six
organizational findings are artifacts of the completed refactor; the surviving open
finding is `large_method`, intentionally not acted on.

## Follow-ups

- `frontend/src/index.css:432` comment still says "ZaloIntegrationPage's" — protected
  path; one-line maintainer edit when next approved.
- `ZaloIntegrationPage.test.ts` filename; rename alongside its module if
  `zaloUpdatePayload` is ever relocated.
- Optional DRY candidate only if a refreshed report flags it: shared test-connection
  button (pending-ternary `settings-test-button`, e.g. Facebook page :435-443).
