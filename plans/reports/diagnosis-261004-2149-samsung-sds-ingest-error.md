# Diagnosis — Samsung SDS "Lỗi nạp" badge (prod)

Date: 2026-10-04 · Project: `samsung-sds` (28496431-46dc-4b13-a23c-a2dc8bc4e698) · Prod image: `tinghire-be:1b17fdbb` (= local HEAD)

## Outcome first

The badge was truthful: the project's freshest knowledge artifact was a failed
training upload, so `ingest_state = "error"`. The owner's re-upload of
`kb-samsung-sds.md` on 04 Oct published successfully at 13:59:05 UTC (20:59 VN),
so the badge now computes `ready` → "Đã nạp" (a page refresh shows it). The bot
never stopped answering: the 12/12 active categories are the 01 Oct content and
today's chunks are indexed.

## Root-cause chain (all steps verified against prod data)

1. 02 Oct 14:32 UTC — operator uploaded `samsung-sds.md` as a project-training
   document (`2ae00f0f`).
2. 15:07:37 — the training run staged 12 category revisions in one flush and
   prepared them sequentially (8 child docs created). The insurance category
   failed the pre-activation retrieval self-test: a record labelled
   `"BHXH, BHYT, BHTN"` measured own-record similarity 0.42 < the 0.45
   name-fallback floor (`RETRIEVAL_SELFTEST_TITLE_FLOOR`,
   `retrieval_selftest.py:52`). That record is the exact acronym-list case the
   module docstring warns about (≥5 letters, so it is tested, and fails).
3. The run aborted. The orchestrator has **no rollback**: the training doc was
   marked FAILED, but 8 prepared revisions stayed PROCESSING (attempt_count=1),
   3 revisions stayed STAGED (attempt_count=0), and 8 child docs stayed
   PROCESSING. No lease, no processing_started_at on the revisions; the queue
   is empty — nothing will ever pick them up. Several deploys since (02–04 Oct)
   have restarted the workers without any recovery sweep.
4. Badge semantics (`_ingest_states_by_project`,
   `backend/app/services/project/service.py:129`): training-tagged artifacts are
   excluded, but the training document itself is not — it was the freshest
   non-training artifact (02 Oct 15:07) with status FAILED → `error`.

## Product gaps this exposed

- **No batch rollback on training failure.** A failed or worker-killed training
  run leaves its claimed revisions in PROCESSING forever. Per-category repair is
  refused for training-owned revisions (deliberate, ConflictError), and the
  designed retry ("thử xử lý lại tệp đã lưu") re-runs the whole batch — which
  would fail again at the same insurance record (self-test floors unchanged
  since 02 Oct). Content fix: rename that record so its label is not a bare
  acronym list.
- **No recovery sweep for orphaned in-flight ingest work**, unlike chat turns
  (`reconcile_worker`). Any deploy that kills `worker-ingest`/`worker-category`
  mid-job orphans the document/revision silently. A 6-job `rq:failed:ingest`
  registry from 01 Oct 16:25–28 shows retries also die there without surfacing.
- Today's ingest took ~16 minutes: both digest sections fell back to the
  deterministic path ("knowledge unit has no matching source quote") after the
  LLM digest failed twice. Working as designed, but slow and worth watching.

## Leftover prod state (verified, harmless to the badge)

- Doc `2ae00f0f` samsung-sds.md FAILED (02 Oct training file).
- 8 child docs PROCESSING (train=2ae00f0f), created 02 Oct 15:07:39–47.
- Revisions: 8 PROCESSING (attempts=1), 3 STAGED (attempts=0), 1 insurance
  FAILED (`category_retrieval_selftest_failed`).
- All are training-tagged, so the badge/count queries exclude them; they only
  keep the saved training file looking in-flight.

## Options proposed to owner

1. Build the code fix: roll the batch back on training failure (claimed
   revisions → FAILED with the real cause) and/or a scheduler sweep that fails
   training-owned artifacts whose lease expired; plus a stale-ingest sweep.
2. Also clean the stuck 02 Oct rows on prod (backup first, then status flips).
3. Document only.

## Resolution (owner chose 1 + 2, same evening)

Code (9b9d860b + 48181091, deployed):

- `app/services/knowledge/recovery_sweep.py` — `recover_abandoned_ingest_work`.
  A training batch whose lease is gone (expired or cleared) and whose document
  sat past a one-day grace window is declared abandoned: the training document
  (if still in-flight), its STAGED/PROCESSING revisions (stamps cleared,
  `quality_result` stripped to the ownership key so a retry re-prepares
  instead of dead-ending on the evidence guard), and its prepared child
  documents all flip to FAILED. Plain documents and non-training revisions
  flip once provably orphaned: past twice the RQ ingest budget (3600s×2) with
  an expired or missing claim lease. The lease outranks the RQ budget
  (3900s > 3600s), so an expired lease can never race a live run.
- `app/workers/knowledge_recovery_worker.py` — maintenance-queue tick every
  `knowledge_recovery_interval_seconds` (1800s), non-reentrancy lock like the
  reconcile tick. Registered in `app/main.py` lifespan.
- Tests: `backend/tests/test_knowledge_recovery_sweep.py` (11 cases,
  including the classification table and both bulk-update predicates). The
  tests caught one real bug pre-deploy: the sweep initially `await`ed
  `db.scalars`, which is not awaitable on a real AsyncSession.

Data repair (04 Oct ~15:05 UTC, after backup):

- Backup: `/opt/vfic/pre-migration-dumps/vfic-kb-repair-261004.dump`
  (pg_dump of knowledge_documents, knowledge_category_revisions,
  knowledge_categories). Restore with `pg_restore -U vfic -d vfic --clean
  --if-exists -t knowledge_documents -t knowledge_category_revisions -t
  knowledge_categories <dump>` inside the postgres container.
- Transaction flipped the 02 Oct leftovers to the exact states the sweep
  writes: 11 revisions (`training_run_abandoned`, evidence stripped) + 8
  child documents (Vietnamese interrupted-run message). The training document
  itself was already truthful (the graceful path had failed it).
- Verified after: zero in-flight documents or revisions for the project;
  badge input = PUBLISHED `kb-samsung-sds.md` (13:59 UTC) → `ingest_state =
  "ready"` → the card shows "Đã nạp". The old "Lỗi nạp" snapshot clears on a
  page refresh.

## Addendum — the meals deadlock and the per-category card (04–05 Oct night)

After the repair the owner's screenshot showed one remaining red card:
"Bữa ăn — Cập nhật lỗi — nội dung cũ vẫn đang dùng". Root cause chain, all
verified on prod:

1. Today's canonical re-import (`kb-samsung-sds.md`) refreshed **11 of 12**
   categories at 13:59 (new ACTIVE revisions, insurance included — its
   serving record has the proper "Chế độ: … BHXH, BHYT, BHTN" label). The
   meals section was byte-identical to 02 Oct, so `stage` reused the failed
   training-batch revision instead of creating a new one.
2. That revision still carried the batch's ownership key and its prepared
   child document still held the `category_revision_id` unique key, so every
   activation path was blocked. Attempting it surfaced a second gap: the
   generic handler in `KnowledgeCategoryService.activate_revision` swallowed
   the real exception (`raise … from None`, no log) — the unique-violation
   cause was only found by re-running the activation steps by hand.
3. Prod fix (backed up first): stripped the ownership key, released the
   child document's `category_revision_id`, re-enqueued through the product's
   own category queue. `meals rev4` activated at 15:59:49 UTC; all 12
   categories now have ACTIVE latest revisions and the card reads clean.

Code shipped for the underlying gaps (commit `a46cf7fb`):

- `recovery_sweep._abandon_training_batch` now strips ownership from **all**
  the batch's revisions — FAILED ones keep their original failure code but
  lose the blocking key — and releases the prepared child documents'
  `category_revision_id` links, so an abandoned batch can never deadlock a
  later activation again. Regression-tested.
- `activate_revision` logs the swallowed exception (with revision id and
  category key) before raising the stable code.

Open follow-up (owner's call, not built tonight): the LLM extraction authored
the bad `"BHXH, BHYT, BHTN"` label on 02 Oct and nothing repairs it — a
bounded LLM rewrite of self-test-offending record labels inside `prepare`
(rewrite → re-embed → re-test, N attempts, then fail with the real error)
would close that class.

## Addendum 2 — the LLM self-repair loop (owner approved, built same night)

Owner asked whether KB import should be all-LLM; decision recorded here:
no — the two-path architecture stands (LLM authors canonical content from
freeform sources; the deterministic engine validates, embeds and activates).
What was missing is LLM self-review, shipped in `b712d87b`:

- `TrainingCategoryBatch.prepare` now runs up to
  `SELFTEST_REPAIR_MAX_ATTEMPTS` (2) repair rounds when the retrieval
  self-test rejects a record: each round asks the json extractor to rewrite
  the offending record's query-like field (`question`/`title`/`name`),
  grounded in the record's own content and forbidden from inventing facts,
  then re-renders, re-embeds and re-tests. A round that changes nothing ends
  the loop immediately; after the bound the batch fails with the real
  self-test error exactly as before.
- On success the repaired document is persisted into the revision
  (`source_markdown`, `normalized_payload`, `content_sha256` via
  `category_checksum`) before the prepared evidence is written, and
  `quality_result.selftest_repair_attempts` records how many rounds ran.
- The raised `CategoryActivationError` now carries the row's stable failure
  code (mirrors `KnowledgeCategoryService.activate_revision`), instead of
  the default code for every cause.
- Tests: `backend/tests/test_selftest_repair.py` (7 cases: label rewrite,
  unusable-LLM stop, non-offending records untouched, value parsing,
  happy-path persistence, one-round stop, bounded attempts). Caught two
  real bugs pre-deploy: `category_checksum` takes a document, not markdown,
  and the raised error always carried the default code.
