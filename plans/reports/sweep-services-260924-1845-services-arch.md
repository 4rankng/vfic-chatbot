# Services-architecture sweep report (ARCH-01/02/03/08/12/15/16)

Lane: backend services architecture (sweep-services). All seven tickets are
closed with the checkpointed WIP verified, finished, and extended; the full
unit lane ends at 2318 passed / 5 failed, with every failure attributed to
another lane (2 frontend layer-boundary edges, 3 deployment-Makefile tests on
the ops lane's IMAGE_TAG change). Ruff is clean across everything this lane
touched.

## Per-ticket outcomes

**ARCH-01 — ingestion subsystem with no production entry point: DONE.**
Deleted the sixteen test-only modules of `services/ingestion/` (template
service/ingestion/compiler, extraction pipeline, fact repository, projector,
review, state machine, normalization, classification, validation, source
blocks, structured-LLM extraction, reference templates, recruitment adapter)
plus their fourteen test files, ~4,800 lines. Kept `limits.py` — the ticket's
evidence missed that four production files import it (api/personas,
api/knowledge, api/webhooks, knowledge/service); it is trimmed to the two
live ingress gates (upload + webhook-body ceilings) and `bounded_batches`
went with its only caller. `test_universal_platform_characterization.py` was
surgically trimmed (two template-only tests deleted, compile_template
assertions dropped from the fixture test). The `IngestionTemplate*` models
stay: they are schema mirrors still read by installation validation.
Commit: the change is inside **fe565f9d** — another lane's kanban commit
swallowed my staged files before my commit landed (incident reported; message
text for the intended commit was handed to the lead for the completion
record). No history rewrite since the commit has descendants.

**ARCH-02 — structured-fact subsystem write-only, canonical FAQ read path
dead: DONE (option (a), per the user-approved direction).** Deleted
`knowledge/publishing/` (publisher, the only caller of `publish_contract`)
and `knowledge/tools/` (domain_tools: get_benefits/get_working_hours/
get_job_requirements/get_job_locations/get_faq_entry) with their two test
files; both ends of the provenance subsystem are now gone. The chunk-based
FAQ is documented as canonical in a runtime-status note atop
`models/provenance.py` (ProjectFaqService → KnowledgeChunk(category='faq') →
services/retrieval), including a do-not-add-readers warning. Commit
**f591f5ce**.

**ARCH-03 — dead parallel turn dispatcher: DONE.** The checkpointed WIP had
already deleted `services/chatbot/`, its tests, and the two budget config
keys (config.py:306-308 carries the explanatory comment). This lane finished
the removal: the vestigial `deadline` parameter and `_run_vector_arm`
time-boxing were deleted from `retrieval/repository.py`'s `match_documents`
(no production caller ever passed a deadline), the stale docstring reference
to `app.services.chatbot.deadlines` is gone, and the docstring now states
that turn time-boxing is queue-level deadline-at-epoch only. Concurrent
vector/lexical arms and the degradation flag unchanged. Commit **acabbd38**.

**ARCH-08 — retrieval repository god module: DONE.** Split
`retrieval/repository.py` (1015 LOC) into `document_repository.py` (memory
match + hybrid document retrieval, ANN gate, chunk visibility, fusion),
`faq_repository.py` (the two canonical FAQ arms), `catalog_repository.py`
(project/persona catalog, job features, income summary, plus
`RecommendationQueries` — the default `RecommendationQueryPort`
implementation that resolves the lead once and carries the page scope), and
`timetable_repository.py`. `repository.py` is now a facade with the same
constructor and public surface; it accepts an injected recommendation query
object, so `recommend_jobs_for_lead`/`list_active_jobs` no longer construct
`RecommendationRepository`/`LeadRepository` inside method bodies. Floors and
the ANN gate remain reachable as facade aliases for the characterization
tests, which were repointed at the owning modules with assertions unchanged
(coordinated with and verified by perf-retrieval). Commit **2c661665**.

**ARCH-12 — bot_path god file: DONE.** The WIP had created
locking/send_claim/bot_outcome/reconcile as dead copies and a follow-up
commit deleted them; this lane did the extraction for real:
`conversation/locking.py` (acquire/release/renew/break_stale),
`send_claim.py` (recheck_ownership, claim_send, finalize_outbound_dispatch),
`bot_outcome.py` (record_bot_outcome, record_bot_pending,
mark_stale_pending_failed), `reconcile.py` (resolve_unconfirmed_sending) as
mixins composed into `BotConversationState`, which keeps the webhook-side
primitives and the proactive path. Every method moved verbatim (verified by
an AST-source diff against HEAD) except the lock TTL default, which now
resolves through cached `get_settings()` per call instead of an import-time
snapshot of the same object. The runtime-surface inventory follows the two
outbox call sites that moved; broad digest re-pinned with ledger comments
(10/119/42 — the provider 122→119 delta is the graph lane's clients.py
split, also ledgered). Commit **5d4633b3**.

**ARCH-15 — outbox row lifecycle vs provider dispatch: VERIFIED COMPLETE, no
change needed.** The checkpointed WIP completed this split:
`outbox_service.py` is a pure facade over `outbox/repository.py` (row
lifecycle: insert/upsert, PENDING claim, sweeps, projections) and
`outbox/dispatcher.py` (the only provider-facing part: neutral + Facebook
dispatch, OA token refresh, authority fence, send-window policy), with a
call-time facade indirection that keeps existing monkeypatching working.
Confirmed structurally against the ticket and green in the suite.

**ARCH-16 — installation service interleaving: DONE.** Split
`installation/service.py` (1074 LOC) into `validation.py` (revision CRUD,
fail-closed validation battery, evidence-currency checks, secret gate),
`lifecycle.py` (authority-locked activate/rollback/suspend/resume plus the
cache-first runtime resolution hot path), and `projection.py`
(runtime/admin views, readiness derivation, public allow-lists) as mixins;
`service.py` keeps the constructor, shared helpers, and `ActiveInstallation`.
Pure move verified by AST-source diff; the only adaptations are stringified
return annotations and two lazy `ActiveInstallation` imports avoiding the
circular import into the composition root. Commit **2b174bb1**.

## PERF contracts verified preserved

- **PERF-01 (cache-first resolve_active + invalidate fence):** the fast path
  (get_cached_fingerprint hit → revision/pack/KB re-check → early return) and
  the commit-then-`_invalidate_cache_safely()` ordering moved byte-identical
  into `lifecycle.py` (the only diffs are the annotation string and the lazy
  import); `test_runtime_authority_stamps`, `test_installation_service`, and
  the access-policy suite pass unchanged.
- **PERF-03 (column-scoped ownership refreshes):** `recheck_ownership` moved
  verbatim including the `_OWNERSHIP_REFRESH_COLUMNS` contract docstring; the
  refresh itself lives in the graph runner (other lane) and its target method
  is unchanged.
- **PERF-08 (distance-once retrieval SQL):** the vector SQL moved
  character-for-character (verified by the AST diff and independently by
  perf-retrieval); `test_retrieval_repository_sql` pins it green.
- **PERF-14 (resolve-lead-once):** `recommend_jobs_for_lead` resolves the
  lead exactly once via `RecommendationQueries`; code identical, now
  injectable through the port seam.

## Incidents (both reported to the lead in real time)

1. My staged ARCH-01 work was swallowed by another lane's `chore(kanban)`
   commit (fe565f9d) — content verified good, message mislabeled; intended
   message text supplied for the completion record.
2. I accidentally `git stash`ed the shared tree during a diagnostic; my files
   were restored, other lanes' in-flight edits were preserved and the lead
   neutralized the stash into tag `stash-rescue-260924`.

## Deferred / hand-offs

- `ProjectKnowledgeQueryPort` still declares the recruitment-flavored
  `job_features_for_project`/`income_summary_for_active_projects`; shedding
  them requires editing `project_knowledge/application/retrieval.py` +
  `graph/ports.py` (other lanes' files). The retrieval side is ready.
- The graph factory still constructs `RetrievalRepository` without injecting
  a `RecommendationQueryPort` (default adapter used); wiring the factory
  belongs to the graph lane, and any injected port must honor the page-scope
  contract documented on `RecommendationQueries`.
- The provenance tables remain physically in the DB (models mirror the
  Alembic schema; no migration per ticket). A future migration may drop
  them; the models now say so.
- Baseline failures owned elsewhere: 2 frontend boundary edges, 3
  deployment-Makefile tests, and the graph lane's in-flight clients
  decomposition transiently broke 4 `test_parallel_tools` tests mid-sweep
  (their `_prefetch_tool` dispatch keyword churn; not from this lane).

Status: DONE
Summary: All seven services-architecture tickets closed across five commits
(f591f5ce, acabbd38, 2c661665, 5d4633b3, 2b174bb1, plus ARCH-01's content
inside fe565f9d); unit lane 2318 passed with the 5 remaining failures all
attributed to other lanes, ruff clean, and PERF-01/03/08/14 contracts
verified intact.
Concerns: ARCH-01's landing commit carries a kanban-only message (content
correct, attribution recorded); the fe565f9d mislabel and the stash incident
are documented above and with the lead.
