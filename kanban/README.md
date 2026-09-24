# Tech-debt kanban

Backlog from the read-only codebase audit of **2026-09-24** (HEAD `923b1d3f`, `main`). One file per ticket. Nothing here has been implemented.

**Board:** P0 8 · P1 35 · P2 64 · P3 5 · **Total 112**

## How to use

- Each ticket is self-contained: problem, `path:line` evidence, impact, and a concrete fix with an effort estimate (S ≈ hours, M ≈ a day, L ≈ multi-day).
- Ticket front-matter carries `severity`, `area`, `labels`, `effort`, `status`. Move `status` through `todo` → `doing` → `done` as work proceeds.
- Several tickets are coupled by design; the `Notes` section names the ticket that must land first or alongside.
- Regenerate from data with `python3 kanban/_build.py` after editing the `tickets_*.py` modules (they are the source of truth for the board).

## Health snapshot at audit time

| Signal | Result |
|---|---|
| Backend unit suite | `2243 passed, 42 skipped, 88 deselected` in 23.4 s |
| Backend `ruff check .` | clean |
| Frontend `tsc --noEmit` | clean |
| Backend integration suite in CI | 1 of 29 files |
| Frontend coverage gate | 3 of 425 files |
| Backend coverage measurement | none |
| Tracked repo artifacts | `assets/showoff` ~21.5 MB, `repomix-output.xml` 4.8 MB |
| Dev vs prod Python | 3.14.5 vs `python:3.12-slim` |

The tree is lint-clean and type-clean, so the debt below is structural, not stylistic.

## P0 — Critical — production or data loss risk (8)

| ID | Title | Area | Effort |
|---|---|---|---|
| [DOC-01](DOC-01-openwiki-instructions-md-documents-a-different-product-and-steer.md) | openwiki/INSTRUCTIONS.md documents a different product and steers the wiki agents are told to consult | docs | S |
| [OPS-01](OPS-01-full-droplet-backup-dies-on-a-non-existent-caddyfile-and-restore.md) | Full-droplet backup dies on a non-existent Caddyfile, and restore hard-requires the artifact it can never produce | ops | S |
| [OPS-02](OPS-02-restore-pins-production-to-the-latest-tag-instead-of-the-dump-s.md) | Restore pins production to the latest tag instead of the dump's recorded image tag and never verifies schema compatibility | ops | M |
| [OPS-03](OPS-03-the-primary-make-backup-path-omits-the-key-that-encrypts-integra.md) | The primary make backup path omits the key that encrypts integration credentials, so a restore silently yields undecryptable data | ops | S |
| [OPS-04](OPS-04-no-log-rotation-anywhere-and-no-disk-monitoring-so-disk-full-is.md) | No log rotation anywhere and no disk monitoring, so disk-full is an unalerted total outage | ops | S |
| [TEST-01](TEST-01-ci-and-the-deploy-gate-run-1-of-29-backend-integration-test-file.md) | CI and the deploy gate run 1 of 29 backend integration test files | testing | M |
| [TEST-02](TEST-02-knowledge-ingestion-tests-are-marked-skip-not-integration-so-the.md) | Knowledge-ingestion tests are marked skip, not integration, so they run nowhere | testing | M |
| [TEST-03](TEST-03-backend-coverage-is-never-measured-and-the-frontend-80-gate-cove.md) | Backend coverage is never measured and the frontend 80% gate covers 3 of 425 files | testing | M |

## P1 — High — serious risk, schedule next (35)

| ID | Title | Area | Effort |
|---|---|---|---|
| [ARCH-01](ARCH-01-app-services-ingestion-is-an-18-module-subsystem-with-no-product.md) | `app/services/ingestion/` is an 18-module subsystem with no production entry point | architecture | M |
| [ARCH-02](ARCH-02-structured-fact-provenance-subsystem-is-write-only-at-runtime-an.md) | Structured-fact / provenance subsystem is write-only at runtime and the canonical FAQ read path is dead | architecture | M |
| [ARCH-03](ARCH-03-services-chatbot-paths-budget-deadlines-py-is-a-parallel-turn-di.md) | `services/chatbot/{paths,budget,deadlines}.py` is a parallel turn-dispatch implementation that never runs | architecture | S |
| [ARCH-04](ARCH-04-graph-fast-lane-py-and-the-template-route-strategy-are-unreachab.md) | `graph/fast_lane.py` and the `template` route strategy are unreachable, so every pleasantry costs a full LLM turn | architecture | S |
| [DOC-02](DOC-02-agents-md-routes-to-three-skill-paths-that-no-longer-exist-and-m.md) | AGENTS.md routes to three skill paths that no longer exist and mis-paths the smoke script | docs | S |
| [DOC-03](DOC-03-documentation-drift-cluster-every-checked-claim-in-tech-md-and-c.md) | Documentation drift cluster — every checked claim in TECH.md and codebase-summary.md except one is wrong | docs | M |
| [DOC-04](DOC-04-plans-is-gitignored-while-agents-md-and-the-completion-checklist.md) | plans/ is gitignored while AGENTS.md and the completion checklist mandate writing reports there | docs | M |
| [DOC-05](DOC-05-three-parallel-agent-config-systems-1-858-tracked-claude-files-a.md) | Three parallel agent-config systems, 1,858 tracked .claude files, and a hook that runs twice per prompt | docs | M |
| [DOC-06](DOC-06-repomix-output-xml-is-tracked-at-4-8-mb-although-every-ignore-fi.md) | repomix-output.xml is tracked at 4.8 MB although every ignore file classifies it as generated | docs | S |
| [DOC-07](DOC-07-21-2-mb-of-one-off-marketing-renders-are-tracked-under-assets-sh.md) | ~21.2 MB of one-off marketing renders are tracked under assets/showoff | docs | S |
| [FE-01](FE-01-zalointegrationpage-is-a-2072-loc-module-whose-one-component-own.md) | ZaloIntegrationPage is a 2072-LOC module whose one component owns four product domains | frontend | L |
| [FE-02](FE-02-projectknowledgepanel-mixes-three-data-access-idioms-across-1095.md) | ProjectKnowledgePanel mixes three data-access idioms across 1095 LOC and 21 useState | frontend | L |
| [FE-03](FE-03-the-message-store-never-evicts-a-conversation-and-three-exported.md) | The message store never evicts a conversation and three exported selectors are dead duplicates | frontend | S |
| [FE-04](FE-04-four-overlapping-30-second-polls-of-the-same-needs-attention-end.md) | Four overlapping 30-second polls of the same needs-attention endpoint per open tab | frontend | S |
| [FE-05](FE-05-react-memo-on-the-inbox-row-is-structurally-defeated-by-per-rend.md) | React.memo on the inbox row is structurally defeated by per-render row allocation | frontend | M |
| [OPS-05](OPS-05-production-and-ci-both-ignore-uv-lock-and-29-of-30-backend-depen.md) | Production and CI both ignore uv.lock, and 29 of 30 backend dependencies have no upper bound | ops | M |
| [OPS-06](OPS-06-nothing-scrapes-the-metrics-endpoints-and-there-are-no-alerts-so.md) | Nothing scrapes the metrics endpoints and there are no alerts, so the only signal is the reconcile worker | ops | M |
| [OPS-07](OPS-07-blue-green-deploy-runs-migrations-with-no-pre-migration-dump-and.md) | Blue/green deploy runs migrations with no pre-migration dump and no lock_timeout | ops | S |
| [OPS-08](OPS-08-worker-healthchecks-only-ping-redis-so-a-wedged-worker-reports-h.md) | Worker healthchecks only ping Redis, so a wedged worker reports healthy forever | ops | M |
| [OPS-09](OPS-09-memory-limits-cover-3-of-12-services-and-the-documented-host-siz.md) | Memory limits cover 3 of 12 services and the documented host size contradicts itself | ops | S |
| [OPS-10](OPS-10-every-image-is-a-mutable-tag-and-no-digest-is-pinned-anywhere.md) | Every image is a mutable tag and no digest is pinned anywhere | ops | S |
| [PERF-01](PERF-01-installation-authority-is-re-derived-from-scratch-2-3-per-turn.md) | Installation authority is re-derived from scratch 2–3× per turn | performance | M |
| [PERF-02](PERF-02-allkeys-lru-redis-can-evict-the-llm-semaphore-token-list-and-sup.md) | `allkeys-lru` Redis can evict the LLM semaphore token list and suppress every turn | performance | S |
| [PERF-03](PERF-03-conversation-state-is-re-loaded-3-per-turn-each-load-cascading-3.md) | Conversation state is re-loaded 3× per turn, each load cascading 3–4 SELECTs | performance | M |
| [PERF-04](PERF-04-direct-context-lane-runs-an-uncached-full-kb-scan-every-turn-and.md) | Direct-context lane runs an uncached full-KB scan every turn and re-sends the whole KB as prompt | performance | M |
| [PERF-05](PERF-05-no-provider-prompt-prefix-caching-is-exploited-on-any-llm-call.md) | No provider prompt/prefix caching is exploited on any LLM call | performance | S |
| [REL-01](REL-01-a-partially-delivered-multi-bubble-answer-is-recorded-failed-so.md) | A partially delivered multi-bubble answer is recorded FAILED, so recovery answers again | reliability | M |
| [REL-02](REL-02-blocking-synchronous-redis-runs-on-the-event-loop-in-llm-telemet.md) | Blocking synchronous Redis runs on the event loop in LLM telemetry and the semaphore release | reliability | S |
| [SEC-02](SEC-02-lead-by-id-routes-skip-the-viewer-scope-invariant-idor-on-candid.md) | Lead by-id routes skip the viewer-scope invariant (IDOR on candidate PII) | security | M |
| [SEC-03](SEC-03-no-server-side-logout-refresh-tokens-are-neither-revoked-nor-tru.md) | No server-side logout; refresh tokens are neither revoked nor truly rotated | security | M |
| [TEST-04](TEST-04-the-release-gate-is-real-but-narrow-mislabelled-correctness-and.md) | The release gate is real but narrow, mislabelled correctness, and not wired to deploy | testing | M |
| [TEST-05](TEST-05-no-contract-test-links-the-frontend-data-provider-to-the-backend.md) | No contract test links the frontend data provider to the backend routes | testing | M |
| [TEST-06](TEST-06-no-dependency-or-security-scanning-in-ci.md) | No dependency or security scanning in CI | testing | S |
| [TEST-07](TEST-07-the-vitest-claude-project-matches-zero-files-and-is-never-run.md) | The vitest claude project matches zero files and is never run | testing | S |
| [TEST-08](TEST-08-visual-regression-baselines-are-darwin-only-and-the-visual-proje.md) | Visual-regression baselines are darwin-only and the visual projects are excluded from CI | testing | M |

## P2 — Medium — real debt, plan it (64)

| ID | Title | Area | Effort |
|---|---|---|---|
| [ARCH-05](ARCH-05-graph-clients-py-1626-loc-holds-seven-responsibilities-and-dupli.md) | `graph/clients.py` (1626 LOC) holds seven responsibilities and duplicates `graph/grounding.py` | architecture | M |
| [ARCH-06](ARCH-06-services-integration-settings-py-1208-loc-mixes-crypto-six-provi.md) | `services/integration_settings.py` (1208 LOC) mixes crypto, six provider groups and cache invalidation | architecture | M |
| [ARCH-07](ARCH-07-api-integrations-py-1353-loc-carries-provider-business-logic-inc.md) | `api/integrations.py` (1353 LOC) carries provider business logic, including a raw httpx OAuth POST | architecture | M |
| [ARCH-08](ARCH-08-services-retrieval-repository-py-992-loc-implements-the-whole-ag.md) | `services/retrieval/repository.py` (992 LOC) implements the whole agent read surface and self-constructs its collaborators | architecture | M |
| [ARCH-09](ARCH-09-graph-factories-py-900-loc-does-five-jobs-and-is-grandfathered-o.md) | `graph/factories.py` (900 LOC) does five jobs and is grandfathered out of the import guard | architecture | M |
| [ARCH-10](ARCH-10-api-knowledge-py-calls-private-service-methods-so-the-cutover-gu.md) | `api/knowledge.py` calls private service methods, so the cutover guard is enforced at four call sites | architecture | S |
| [ARCH-11](ARCH-11-over-abstraction-single-implementation-facades-a-mis-declared-pr.md) | Over-abstraction: single-implementation facades, a mis-declared Protocol and a test double in production code | architecture | S |
| [ARCH-12](ARCH-12-services-conversation-bot-path-py-1118-loc-carries-five-responsi.md) | `services/conversation/bot_path.py` (1118 LOC) carries five responsibilities | architecture | M |
| [ARCH-13](ARCH-13-lru-cache-get-settings-plus-seven-import-time-settings-snapshots.md) | `@lru_cache get_settings()` plus seven import-time settings snapshots; `core/db.py` creates the engine at import | architecture | S |
| [ARCH-14](ARCH-14-app-capabilities-is-a-live-registry-with-a-dormant-hash-verified.md) | `app/capabilities/` is a live registry with a dormant, hash-verified extension API | architecture | S |
| [ARCH-15](ARCH-15-services-outbox-service-py-842-loc-mixes-row-lifecycle-with-thre.md) | `services/outbox_service.py` (842 LOC) mixes row lifecycle with three provider dispatch branches | architecture | M |
| [ARCH-16](ARCH-16-services-installation-service-py-1055-loc-interleaves-validation.md) | `services/installation/service.py` (1055 LOC) interleaves validation, lifecycle, projection and checksums | architecture | M |
| [ARCH-17](ARCH-17-the-enforced-architecture-rules-miss-the-real-import-edges.md) | The enforced architecture rules miss the real import edges | architecture | S |
| [ARCH-19](ARCH-19-the-flat-services-duplicate-the-bounded-contexts-in-named-pairs.md) | The flat services duplicate the bounded contexts in named pairs | architecture | L |
| [DOC-08](DOC-08-one-off-probe-and-qa-scripts-are-tracked-in-frontend-qa-although.md) | One-off probe and QA scripts are tracked in frontend/qa although the backend explicitly bans the practice | docs | S |
| [DOC-09](DOC-09-a-164-5-mb-graph-database-is-kept-out-of-git-only-by-a-gitignore.md) | A 164.5 MB graph database is kept out of git only by a .gitignore inside its own untracked directory | docs | S |
| [DOC-10](DOC-10-repo-root-sprawl-22-top-level-entries-8-of-them-generated-or-str.md) | Repo-root sprawl — 22 top-level entries, 8 of them generated or stray | docs | S |
| [DOC-11](DOC-11-core-docs-are-about-two-months-stale-relative-to-the-code-they-d.md) | Core docs are about two months stale relative to the code they describe | docs | M |
| [DOC-12](DOC-12-config-duplication-three-makefiles-two-js-lockfiles-two-hook-con.md) | Config duplication — three Makefiles, two JS lockfiles, two hook configs and rules duplicated across two trees | docs | M |
| [DOC-13](DOC-13-frontend-public-ships-7-7-mb-with-the-same-login-art-committed-t.md) | frontend/public ships ~7.7 MB with the same login art committed three times | docs | S |
| [FE-06](FE-06-confirmed-dead-i18n-catalog-blocks-and-four-self-testing-kit-com.md) | Confirmed-dead i18n catalog blocks and four self-testing kit/ components | frontend | S |
| [FE-07](FE-07-product-code-hardcodes-vietnamese-bypassing-a-catalog-served-by.md) | Product code hardcodes Vietnamese, bypassing a catalog served by two competing providers | frontend | M |
| [FE-08](FE-08-the-no-explicit-any-rule-is-enforced-only-for-flat-globs-and-nev.md) | The no-explicit-any rule is enforced only for flat globs and never for atomic-crm | frontend | S |
| [FE-09](FE-09-externalsourcelist-hand-rolls-a-466-poll-3h40m-polling-state-mac.md) | ExternalSourceList hand-rolls a 466-poll, 3h40m polling state machine | frontend | M |
| [FE-10](FE-10-a-module-scope-socket-port-pulls-socket-io-client-into-the-entry.md) | A module-scope socket port pulls socket.io-client into the entry chunk and never re-auths after JWT rotation | frontend | S |
| [FE-11](FE-11-two-virtualization-libraries-and-manualchunks-still-splits-the-l.md) | Two virtualization libraries, and manualChunks still splits the legacy one | frontend | M |
| [FE-12](FE-12-a-24-hour-gctime-with-no-persister-plus-offlinefirst-mutations-t.md) | A 24-hour gcTime with no persister, plus offlineFirst mutations that can replay | frontend | S |
| [FE-13](FE-13-the-layered-slice-pattern-covers-6-of-22-features-and-the-two-wo.md) | The layered slice pattern covers 6 of ~22 features, and the two worst god files are unlayered | frontend | L |
| [FE-14](FE-14-duplicated-credential-field-machinery-between-the-zalo-and-faceb.md) | Duplicated credential-field machinery between the Zalo and Facebook pages | frontend | M |
| [FE-15](FE-15-dashboard-derivations-are-recomputed-on-every-render.md) | Dashboard derivations are recomputed on every render | frontend | S |
| [FE-17](FE-17-registry-json-is-not-the-generator-s-output-and-registry-check-a.md) | registry.json is not the generator's output and registry:check already fails at HEAD | frontend | M |
| [OPS-11](OPS-11-declared-but-unused-dependencies-and-a-dead-curl-in-the-runtime.md) | Declared-but-unused dependencies and a dead curl in the runtime image | ops | S |
| [OPS-12](OPS-12-documentation-contradicts-the-code-on-operator-critical-knobs.md) | Documentation contradicts the code on operator-critical knobs | ops | S |
| [OPS-13](OPS-13-dev-venv-is-python-3-14-while-production-and-ci-are-3-12.md) | Dev venv is Python 3.14 while production and CI are 3.12 | ops | S |
| [OPS-14](OPS-14-two-copies-of-tanstack-query-core-ship-in-the-frontend-bundle.md) | Two copies of @tanstack/query-core ship in the frontend bundle | ops | S |
| [OPS-15](OPS-15-dev-only-mock-servers-and-the-env-template-ship-into-the-product.md) | Dev-only mock servers and the env template ship into the production backend image | ops | S |
| [OPS-16](OPS-16-nine-migrations-have-fake-or-absent-downgrades-and-no-check-exer.md) | Nine migrations have fake or absent downgrades and no check exercises alembic downgrade | ops | M |
| [OPS-17](OPS-17-later-migrations-create-indexes-non-concurrently-against-live-ta.md) | Later migrations create indexes non-concurrently against live tables | ops | S |
| [OPS-18](OPS-18-make-dev-cannot-work-from-a-clean-clone-and-no-document-says-how.md) | make dev cannot work from a clean clone and no document says how to bootstrap | ops | S |
| [OPS-19](OPS-19-dead-port-plumbing-between-the-root-and-backend-makefiles.md) | Dead PORT plumbing between the root and backend Makefiles | ops | S |
| [PERF-06](PERF-06-turn-preamble-serialises-four-independent-steps.md) | Turn preamble serialises four independent steps | performance | S |
| [PERF-07](PERF-07-connection-budget-exceeds-max-connections-150-and-pool-timeout-3.md) | Connection budget exceeds `max_connections=150` and `pool_timeout=30s` outlives the turn SLA | performance | S |
| [PERF-08](PERF-08-retrieval-computes-the-ann-distance-three-times-per-row-and-the.md) | Retrieval computes the ANN distance three times per row and the memories halfvec index is unused | performance | M |
| [PERF-09](PERF-09-the-retrieval-cache-key-is-non-deterministic-because-active-proj.md) | The retrieval cache key is non-deterministic because `active_project_ids()` has no ORDER BY | performance | S |
| [PERF-10](PERF-10-single-flight-coalescing-can-never-engage-so-the-retrieval-stamp.md) | Single-flight coalescing can never engage, so the retrieval stampede is unmitigated | performance | S |
| [PERF-11](PERF-11-dashboard-runs-whole-history-aggregates-every-30-s-over-a-never.md) | Dashboard runs whole-history aggregates every 30 s over a never-pruned `bot_runs` table | performance | M |
| [PERF-12](PERF-12-three-periodic-ticks-and-the-reconcile-sweep-share-a-single-foll.md) | Three periodic ticks and the reconcile sweep share a single `followup` worker with no depth bound | performance | S |
| [PERF-14](PERF-14-the-lead-row-is-re-resolved-2-3-per-turn-by-every-adapter-that-n.md) | The lead row is re-resolved 2–3× per turn by every adapter that needs it | performance | S |
| [REL-03](REL-03-redis-locks-released-without-an-ownership-check-with-ttls-shorte.md) | Redis locks released without an ownership check, with TTLs shorter than the work they guard | reliability | S |
| [REL-04](REL-04-password-reset-otp-is-sent-by-an-unreferenced-fire-and-forget-ta.md) | Password-reset OTP is sent by an unreferenced fire-and-forget task | reliability | S |
| [REL-05](REL-05-leads-gender-blank-only-guarantee-is-a-read-then-write-toctou-an.md) | leads.gender blank-only guarantee is a read-then-write TOCTOU and the write is unconditional | reliability | S |
| [REL-06](REL-06-outbox-pending-row-is-dispatcher-visible-during-the-inline-send.md) | Outbox PENDING row is dispatcher-visible during the inline send, recording a false ERROR turn | reliability | S |
| [REL-07](REL-07-semantic-cache-scans-all-vectors-in-python-on-the-loop-and-its-s.md) | Semantic cache scans all vectors in Python on the loop, and its scope guard has a hole | reliability | M |
| [SEC-04](SEC-04-rate-limiting-covers-only-the-four-auth-endpoints-webhooks-and-l.md) | Rate limiting covers only the four auth endpoints; webhooks and LLM routes are unbounded | security | M |
| [SEC-05](SEC-05-upload-size-caps-exist-but-are-dead-code-request-bodies-are-read.md) | Upload size caps exist but are dead code; request bodies are read unbounded | security | S |
| [SEC-06](SEC-06-no-security-headers-and-no-csp-jwts-live-in-localstorage.md) | No security headers and no CSP; JWTs live in localStorage | security | S |
| [SEC-07](SEC-07-admin-secret-previews-leak-8-characters-of-every-credential-reve.md) | Admin secret previews leak 8 characters of every credential; reveal endpoint has no step-up | security | S |
| [SEC-08](SEC-08-jwt-validation-omits-audience-issuer-and-required-claims-algorit.md) | JWT validation omits audience/issuer and required claims; algorithm is env-controlled | security | S |
| [TEST-09](TEST-09-implementation-is-pinned-by-inspect-getsource-substring-assertio.md) | Implementation is pinned by inspect.getsource substring assertions | testing | M |
| [TEST-10](TEST-10-40-assertions-test-css-and-tsx-source-text-instead-of-rendered-l.md) | ~40 assertions test CSS and TSX source text instead of rendered layout | testing | L |
| [TEST-11](TEST-11-wall-clock-timing-assertions-in-the-unit-lane-will-flake-on-a-sl.md) | Wall-clock timing assertions in the unit lane will flake on a slow runner | testing | M |
| [TEST-12](TEST-12-the-unit-lane-has-no-outbound-network-guard-although-the-integra.md) | The unit lane has no outbound-network guard although the integration lane does | testing | S |
| [TEST-13](TEST-13-56-migrations-8-with-roundtrip-coverage-and-none-of-those-run-in.md) | 56 migrations, ~8 with roundtrip coverage, and none of those run in CI | testing | L |
| [TEST-14](TEST-14-e2e-is-a-2-test-smoke-and-the-highest-blast-radius-journeys-are.md) | E2E is a 2-test smoke and the highest-blast-radius journeys are mock-only | testing | M |

## P3 — Low — hardening / cleanup (5)

| ID | Title | Area | Effort |
|---|---|---|---|
| [ARCH-18](ARCH-18-import-time-registry-validation-with-failure-semantics-and-dorma.md) | Import-time registry validation with failure semantics, and dormant `models/case.py` tables to record rather than drop | architecture | S |
| [FE-16](FE-16-unreachable-english-i18n-default-unused-dependencies-and-an-unsc.md) | Unreachable English i18n default, unused dependencies, and an unscoped global CSS surface | frontend | S |
| [OPS-20](OPS-20-low-severity-restore-backup-dev-exposure-release-gate-and-migrat.md) | Low-severity restore, backup, dev-exposure, release-gate and migration-naming hygiene | ops | S |
| [PERF-13](PERF-13-embedding-cache-key-is-un-normalised-and-each-entry-is-60-kb-of.md) | Embedding cache key is un-normalised and each entry is ~60 KB of JSON | performance | S |
| [TEST-15](TEST-15-sleep-pumped-synchronization-deploy-makefile-test-fakes-and-ast.md) | Sleep-pumped synchronization, deploy-Makefile test fakes, and AST-structure pins | testing | S |

## By area

| Area | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| Security | 0 | 2 | 5 | 0 | 7 |
| Reliability | 0 | 2 | 5 | 0 | 7 |
| Performance | 0 | 5 | 8 | 1 | 14 |
| Architecture & dead code | 0 | 4 | 14 | 1 | 19 |
| Frontend | 0 | 5 | 11 | 1 | 17 |
| Testing & CI | 3 | 5 | 6 | 1 | 15 |
| Ops, deploy & data | 4 | 6 | 9 | 1 | 20 |
| Docs & repo hygiene | 1 | 6 | 6 | 0 | 13 |

Counts here derive from each ticket's single `area` field, not from `labels`, which may carry cross-cutting areas — e.g. SEC-02 and SEC-05 sit in the Security row but are also labeled `reliability`, so a label-based Reliability count reads 29, not 7.

## Suggested first wave

Ordered by risk-per-hour, not by severity label:

1. **SEC-02** — thread the viewer through the lead by-id routes; one file, closes whole-tenant candidate-PII exposure.
2. **OPS-01 / OPS-02 / OPS-03** — the disaster-recovery path is non-functional and the credential encryption key is not backed up.
3. **PERF-02** — a Redis eviction policy that can silently suppress every turn.
4. **TEST-01** — widen the CI integration lane from 1 file to 29; the invariants are already written and currently unenforced.
5. **REL-01** — a partial multi-bubble delivery that makes the bot answer the candidate twice.

## Deferred by request

Findings the audit confirmed but which are **deliberately not ticketed yet**. Recorded here so they are not lost or re-discovered from scratch.

**Unauthenticated Zalo OA webhook.** `POST /webhooks/zalo/oa` (`backend/app/api/webhooks.py:107-165`) performs no authentication of any kind — signature verification was deliberately disabled because the stored credential is the wrong Zalo secret (`backend/app/api/webhooks.py:138-146`). Any unauthenticated caller can create conversations, create and update leads, and enqueue real LLM turns: dedup is per `(sender, msg_id)`, so looping fresh sender ids yields unbounded cost against `llm_concurrency_limit = 8` on a 2 vCPU box. It is the only credential-free state-changing endpoint in the application.

Root cause: the app holds the OA *access-token* secret rather than Zalo's webhook checksum key, so the (correct) verifier at `backend/app/services/zalo_oa_signature.py:verify_signature` could never pass. Fixing the code without fixing the credential would false-reject 100% of real events. Either obtain the checksum key and wire the verifier into the inbound route, or delete the route if the OA channel is not in production use.

### Withdrawn ticket ids

The id sequence is deliberately **not** contiguous: the finding above was allocated an id, then withdrawn by request before the board was published, and no id is renumbered. The gap SEC-02…SEC-08 is intentional — no ticket is missing or lost.

- **SEC-01 (withdrawn)** — Unauthenticated Zalo OA webhook (`POST /webhooks/zalo/oa`) — deferred by request, not counted on the board. The stored credential is the OA *access-token* secret rather than Zalo's webhook checksum key, so wiring the (correct) verifier in without the matching credential would false-reject 100% of real OA events.

## Not tickets

Findings the audit deliberately records as *not* defects, so they are not re-litigated:

- The layering rules (`API → Services → Models/Core`, `graph/` behind `graph/ports.py`) are machine-enforced with a zero-entry allowlist and are not violated.
- The pre-send ownership claim (`claim_send`) is genuinely atomic; the outbox claim cannot double-send.
- Raw SQL is static or whitelist-built; no SQL injection, XXE, path traversal, or SSRF was found.
- No hardcoded secrets; `backend/.env` is untracked and ignored; credential-bearing transport loggers are silenced.
- Socket.IO enforces per-room authorization on connect and on every join.
- `assets/showoff`, `openwiki/`, and `kb/` are tracked but were classified as artifacts by other ignore files — the fix is a `.gitignore` rule, not a rewrite.
