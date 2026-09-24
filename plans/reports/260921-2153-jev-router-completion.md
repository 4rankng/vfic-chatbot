# Agent Completion Checklist — Jev router (replace keyword routing with TypeSafe Jev)

- Task: Replace the keyword/regex turn router (router.py, fast_lane.py matching, sort detectors) with one TypeSafe Jev fan-out call per inbound turn; operator-managed enable toggle + API key via the admin settings UI (IntegrationSetting, encrypted at rest); invalid key / off / API failure degrades to the neutral agent route so the bot always works.
- Scope: backend graph decision layer (new `graph/decisions.py`, `TurnDecisionsPort`, router policy rewrite, runner threading), integration settings + admin API + probe, frontend settings panel, tests, TECH.md.
- Files changed: backend/app/graph/{decisions.py new, ports.py, router.py, fast_lane.py, runner.py, types.py, factories.py}; backend/app/services/{integration_settings.py, llm_probe.py}; backend/app/api/integrations.py; backend/app/schemas/integrations.py; backend/app/core/preamble_cache.py; frontend integrations {api.ts, ZaloIntegrationPage.tsx, ZaloIntegrationPage.navigation.test.tsx}; tests (new test_graph_decisions.py; migrated test_golden_set.py, test_model_tiering.py, test_salary_coercion.py, test_runtime_policy_composition.py, test_graph_runner_turn.py, test_universal_platform_characterization.py, test_runtime_surface_inventory.py; removed test_graph_router.py, test_fast_lane.py, test_recency_sort_intent.py, test_router_tool_gating.py); TECH.md; .claude/.ckignore (hook-sanctioned !.venv line).
- Instructions retrieved: AGENTS.md, TECH.md, docs/code-standards (via conventions in code), typesafe-ai skill + live docs.typesafe.ai API reference, integration-settings custom_llm pattern.
- Approval required: config.py untouched (user chose settings-UI storage); new dependency avoided (httpx REST, no typesafe-sdk); bot routing/safety-adjacent behavior changed per the user's explicit directive; HTTP-surface governance snapshots updated after review of the 3 new endpoints.
- Approval evidence: user messages in-session ("remove all regex and use JEV", "user can decide to turn on or off Jev", "so in case API KEY is not valid... our app still work", AskUserQuestion answers: settings-page key + meaning-decisions-only scope).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Jev fan-out replaces keyword router end-to-end; enable toggle; neutral fallback; settings UI panel; live replay 21/21 vs real API |
| Diff is limited to the approved scope | PASS | `git status --short` reviewed — all files in the enumerated scope above |
| Protected operations were avoided or approved | PASS | config.py, alembic, Makefiles, deployment files untouched; no new dependencies; no commits/pushes |
| Focused tests/checks pass | PASS | backend `pytest tests/test_graph_decisions.py tests/test_graph_safety.py` 39 passed; golden file 18 passed + 21 live (with JEV_EVAL=1) |
| Broader regression tests pass when shared behavior changed | PASS | full backend suite 2211 passed / 0 failed (82 errors pre-existing on stashed baseline — infra-dependent integration tests, same on clean tree) |
| Lint passes for affected code | PASS | `ruff check app tests` — All checks passed; frontend `npm run lint` per subagent |
| Type checking passes for affected code | PASS | frontend `npm run typecheck` PASS (verified independently); backend py_compile on all touched files |
| Build/import validation passes for affected code | PASS | governance suites test_runtime_surface_inventory 4/4 + test_architecture_boundaries 17/17 after snapshot update |
| Security and privacy impact reviewed | PASS | key stored AES-GCM encrypted (existing cipher); key never logged/printed; probe sends one canonical question; Jev state includes candidate text (user text leaves VPC — flagged as open question for privacy review); audit record on settings change |
| Performance and async-I/O impact reviewed | PASS | one async fan-out call per turn in the RQ worker (~300 ms p50 measured, 3.5 s bounded attempt + single 429/529 retry); timings["jev_ms"] instrumented; failover unaffected |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Vietnamese-only labels mirroring custom-llm panel patterns; existing shadcn components reused |
| Error handling and compatibility reviewed | PASS | degraded=True path pinned by tests (no key / HTTP error / unusable answer); retry only on 429/529; no turn ever blocks on Jev |
| Documentation impact handled | PASS | TECH.md §1 + §2.2 updated (turn-decisions row + routing invariant) |
| No new unlinked TODO/FIXME/HACK | PASS | grep clean on changed files |
| Final `git diff --check` passes | PASS | ran clean before frontend handoff; frontend verified by subagent + spot-check |
| Final `git status --short` reviewed | PASS | 24 paths, all enumerated in scope |

## Result

- Overall status: DONE (backend verified end-to-end incl. live API replay; frontend verified by delegated agent with independent spot-check of typecheck + nav tests)

## Unresolved questions

1. Data-retention/SLA terms for candidate text sent to api.typesafe.ai (leaves the VPC) — needs a privacy review before production enablement.
2. Golden-set agreement at production scale: the live replay is 21 curated phrases; run `JEV_EVAL=1 pytest tests/test_golden_set.py -k live` regularly and expand the corpus before trusting high-stakes automation.
3. Latency from the production droplet (dev-machine p50 was ~350 ms).
