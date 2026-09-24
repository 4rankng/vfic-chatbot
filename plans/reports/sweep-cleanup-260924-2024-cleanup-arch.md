# sweep-cleanup — ARCH-04 / ARCH-10 / ARCH-11 / ARCH-19

**Outcome:** all four cleanup tickets are delivered. ARCH-04 deleted the unreachable
template fast lane end to end (five commits, net −700 lines of dead routing,
templates, and a dead Jev question). ARCH-10 kept the cutover guard but moved it
onto public service surface after proving the audit's deletion suggestion would
have silently bypassed the rule. ARCH-11 removed three stacked single-implementation
facades plus the one-method Protocol, and relocated the production-shipped test
double into `tests/helpers/`. ARCH-19 landed the honest increment — the KB service
file pair is folded into the knowledge context and the twin text normalizers are one
pipeline — with the remainder staged below. The unit lane stands at 2299 passed /
24 skipped; the only two failures are the two frontend boundary tests that fail on
sweep-fe's untracked working-tree files and fail identically without any of my
changes.

## Commits

| Ticket | Hash | Note |
|---|---|---|
| ARCH-04 | `c097cb46` | fast-lane removal (see incident note) |
| ARCH-04 | `94ed3615` | model-tiering pin inverted to agent lane |
| ARCH-10 | `49c91fb6` | public guards, behavior unchanged |
| ARCH-11 | `2644d841` | facades + Protocol deleted, double moved out of app/ |
| ARCH-19 | `db7611f4` | KB service into the knowledge context, normalizers merged |

## ARCH-04 — template fast lane deleted (c097cb46, 94ed3615)

**Deletion evidence (reachability proven impossible).** I searched every consumer of
`route.strategy` in `app/`: the only production readers are `should_use_fast_model`
(router.py:46) and the `timings["route_strategy"]` telemetry copy at
runner.py:375. Nothing branches on `"template"` to return a canned reply — the
`_agent_turn`/`_resolve_lane` path has no template early return, and the
runner.py:1468–1477 comment records the product decision ("every normal user message
reaches the LLM") that makes the lane un-wirable without reversing that decision.
`template_for`/`fast_lane.py` was imported by three test files only;
`TurnDecisions.pleasantry_kind` was populated by the Jev fan-out and read by nothing
in production. Every pleasantry therefore cost a full LLM turn anyway — the lane only
advertised a short-circuit that could not fire.

**Removed:** `app/graph/fast_lane.py`; the `"template"` member of `TurnStrategy` and
`FAST_MODEL_STRATEGIES` (router.py); `TurnDecisions.pleasantry_kind`
(graph/ports.py); the `pleasantry_kind` Jev question, criteria, and parsing
(graph/decisions.py) — one fewer question in the per-turn fan-out; the small_talk
branch now emits `strategy="agent"` with the new `small_talk_terms` trace reason
(added to `DecisionTraceSummaryCode` + route_selected summaries in schemas/bot_run.py,
additive). `"fast_lane_match"` stays parseable for historical decision traces stored
in `bot_runs.decision_trace` (the schema parses v1/v2 history). The runner comment at
the former lane site keeps recording why there is no template short-circuit. Prompt
content untouched — the only Jev change is removal of a dead question; small_talk
still gets its routing instruction to the LLM.

**Incident (honest disclosure, attribution corrected).** Commit c097cb46 contains 23
files, not my 9: a staging race — I verified `git diff --cached` showed exactly my
paths, but another lane's `git add` landed in the window before my `git commit`
executed, so the integration_settings module→package split (ARCH-06 owner's work,
14 files) landed inside my commit under my message. I first misattributed it to
sweep-services; they corrected me — their lane's footprints are acabbd38, f591f5ce,
2c661665, 5d4633b3 (the earlier bc0c3458/119 broad-digest pin), 2b174bb1, fe565f9d,
and they never touched integration_settings. The split's content was green on the
shared tree (I had just run the graph and boundary suites) and I did not reset
shared history mid-sweep. The ARCH-06 owner's report should reference c097cb46 for
their split. All my remaining commits use `git commit --only <paths>`, which is
immune to this race.

## ARCH-10 — cutover guard onto public surface (49c91fb6)

The audit's suggested fix ("delete the router calls — the guards already run inside
ingest_version/ingest_document") is **wrong for the document path**: I traced
`_project_knowledge_jobs.ingest_document` → `SqlAlchemyKnowledgeIngestionAdapter.ingest_document`
→ `KnowledgePipeline.run` and there is no `_require_legacy_mutation_allowed` anywhere
in that chain (only the version path re-guards, inside `KnowledgeService.ingest_version`).
The router's guard calls at process/reindex were the only synchronous enforcement of
the cutover rule on those routes; deleting them would have created exactly the silent
bypass the ticket warns about. The applied fix is the ticket's fallback: the router
now calls public `KnowledgeService.assert_mutable(project_id)` and
`require_version(project_id, version_id)` (renamed from the two underscore methods,
12 internal call sites updated, docstrings rewritten to describe the precondition
contract). Behavior is byte-identical — every legacy mutation method still runs the
precondition itself, and the router keeps its fail-fast before enqueueing (a doomed
enqueue instead of a synchronous 409/404 is what deletion would have traded for).

## ARCH-11 — over-abstraction removed (2644d841, −445 lines)

The category lifecycle had **three stacked hops with no behavior anywhere except the
last**: routes (api/projects.py ×8), category_worker, and external_source_sync all
went `CategoryUseCases → SqlAlchemyCategoryAdapter → KnowledgeCategoryService`. The
adapter's explicit wiring (`jobs=build_project_knowledge_jobs()`,
`cache_repair=RedisProjectKnowledgeCacheRepair()`) is byte-equivalent to the
service's lazy defaults in `_job_scheduler`/`_cache_repairer`, so I collapsed the
whole chain: every caller now constructs `KnowledgeCategoryService(db)` directly;
`build_category_use_cases` is gone; external_source_sync no longer builds a second
adapter shape (the "same facade, two different adapters" defect is structurally
impossible now). `KnowledgeIngestionUseCases` (two pure-delegation methods) and the
one-method `ProjectKnowledgeCacheRepairPort` (one impl, no behavioral fake — the
relearn test fakes `bump_kb_caches` by monkeypatch, not this Protocol) are deleted;
the ingestion worker calls the SqlAlchemy adapter through a renamed composition
function `build_knowledge_ingestion`. This went one layer deeper than the ticket's
literal suggestion (keep the adapter, drop the use-cases class) because the adapter
was itself pure delegation — keeping it would have preserved the exact
"indirection with no behaviour to hide" the ticket exists to remove. The two
boundary tests pinning the facades (`_CategoryPort`, `_IngestionPort`) were deleted
with their subjects — fakes that exist only to test the double. `CapabilityAdapter`
(also named by the ticket) was already gone from the tree; nothing to do. The
`InMemoryAccountResolver` double moved from `app/channels/accounts.py` to
`tests/helpers/channel_accounts.py`; `ChannelAccountStatus` stays in app (production
code imports it). Module docstrings updated to match.

## ARCH-19 — first pair delivered, remainder staged (db7611f4)

**Delivered:** the knowledge pair's file-level dedup. `services/knowledge_base_service.py`
→ `services/knowledge/base_service.py` (git rename detected at 100%, byte-identical
move, all 8 importers updated across app and tests, no compat shim — every consumer
is greppable and updated in-commit). Both knowledge services now live in one bounded
context. The two near-identical normalizers in `text_ingestion.py` collapse onto one
`_normalize_kb_text(raw, *, rstrip_lines)` pipeline: `normalize_kb_scalar` is the
shared pipeline plus per-line rstrip; `normalize_kb_text` keeps the exact legacy
Markdown contract deliberately (changing it would rewrite every stored
`content_sha256` — now documented on the method). Both public names and all callers
unchanged. Verified property-wise (legacy lane byte-identical output incl. hashes)
and by the normalizer/migration tests. No inventory re-pin needed: the moved module
carries no httpx marker, so it contributes nothing to the provider-transport scan.

**Staged plan for the remainder (L-effort tail):**

1. **Webhook ingress pair** — `services/webhook.py::ZaloWebhookService` vs
   `channels/ingress.py::ChannelIngressService`: two dedup/ensure/record orderings
   for one "inbound text" concept. The ticket itself sequences this after ARCH-02
   (canonical FAQ/fact path), which is unclaimed; and both entry files
   (api/webhooks.py is a protected path) sit on the bot inbound path where a step
   reordering is a behavior change, not a move. Stage: extract the shared step list
   (dedup → ensure → record) into one owner, converge Messenger onto it, gate with
   the existing conversation-messaging ingress tests. Est. 1–2 days with the ARCH-02
   decision made.
2. **Class-level KnowledgeService/KnowledgeBaseService merge** — the file pair is
   done; merging the two classes' overlapping Project/KB/Document queries behind one
   service is genuinely multi-day (712 + 458 LOC, the `project_id is not None`
   router branch in api/knowledge_bases.py selects full method sets, and the FAQ
   authority question (ARCH-02) changes the target shape). Not staged for code —
   staged for re-ticketing after ARCH-02.
3. **ARCH-17 import edges** — unchanged, per ticket notes sequence after ARCH-02.

## Verification

- Narrow per ticket: graph decisions/golden/persona/golden-dataset (52 passed),
  knowledge API/service/cutover suites (179 passed + 95/165 worker-boundary runs),
  channel conformance + dispatch (part of 165 passed), model tiering (4 passed).
- Full lane (`cd backend && .venv/bin/pytest -m "not integration"`): **2299 passed,
  24 skipped, 2 failed** — both failures are `test_architecture_boundaries.py`
  frontend-layer tests failing on sweep-fe's untracked frontend files
  (`conversation-presentation.ts`, `use-category-draft.ts`); they failed identically
  before my first commit and do not involve backend files.
- ruff clean on all touched files (`ruff check app/` and the touched tests).
- Boundary-snapshot rule: my decisions.py change moves the broad provider-transport
  scan by −2; the re-pin (digest `4ee2dccd…`, provider_boundary 111) landed inside
  c097cb46 with the ARCH-06 owner's split and I verified empirically that it
  includes my delta before discovering the race. Sweep-services' earlier pin was
  the prior digest `bc0c3458…` (119) — the -8 delta from 119→111 is the ARCH-06
  split plus my -2. ARCH-10/19 diffs verified **zero** inventory delta; ARCH-11's
  deletions and the KB move carry no scanned verbs or httpx markers — inventory and
  boundary tests pass at HEAD.

## Unresolved / handoff notes

- The two frontend boundary failures belong to sweep-fe; they will pass or be
  re-pinned by that lane's commit.
- `services/slo_service.py` still carries `'fast_lane'` literals in its telemetry SQL
  (reads historical `stage_timings->>'lane'` values); outside my file ownership, so
  left as-is — safe to drop when fast_lane telemetry ages out of dashboards.
- `backend/.coveragerc` (untracked, sweep-tests' file) untouched.
- ARCH-04's deletion means Jev fan-outs from today carry no `pleasantry_kind`
  question; traces written before this commit remain parseable.

Status: DONE_WITH_CONCERNS

Summary: All four tickets delivered in five commits — dead fast lane deleted with
reachability proven impossible, cutover guard preserved on public surface after
refuting the audit's deletion claim, three facades + a Protocol + a shipped test
double removed, KB service folded into the knowledge context with normalizers
merged; unit lane 2299 passed with only the two pre-existing sweep-fe frontend
boundary failures.

Concerns: commit c097cb46 accidentally contains the ARCH-06 owner's
integration_settings split (staging race, contents green, ARCH-06 owner should
reference c097cb46 — initially misattributed to sweep-services, since corrected);
ARCH-19's webhook-ingress convergence and the class-level KB merge remain staged
pending the unclaimed ARCH-02 decision; two frontend boundary tests fail from
sweep-fe's untracked working-tree files, not my changes.
