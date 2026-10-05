# Project knowledge workflow

Knowledge is owned by a Project, such as LG Display, Samsung, or PQC. A Project chooses one
mode when it is created; the mode does not change after content exists.

## Current ingestion lanes

| Lane | Authoring source | Canonical representation | Activation / retrieval |
|---|---|---|---|
| Direct context | Page text without retired structural fields | Deterministically normalized text plus checksum | Atomic whole-page replace; the focused Project reads the full page |
| Project categories | Markdown per immutable revision without retired structural fields | Strict typed payload plus deterministic checksum | Shadow-only prepare first, then explicit Project-wide cutover to category authority |
| Legacy KB versions | Uploaded document/version | Canonical Markdown is deterministic; free-form input uses the compatibility digest pipeline | Active legacy version remains readable only before category cutover |

The lifecycle vocabulary is shared across lanes:

- **Raw source** retains administrator content; new page and category sources omit retired structural reference fields.
- **Normalized representation** is meaning-preserving deterministic text or structured data.
- A **validated revision** has passed its category's schema checks.
- A **projection** is a derived chunk, Job, route, or stop.
- The **active pointer** selects authoritative content.
- A **derived read model** can always be rebuilt from that authority.

Knowledge records belong to the Project. The retired `job_ids`, `jobs_ids`,
`vacancies` and `employment_type` fields are not part of the KB contract, even
as null placeholders. Older input remains accepted: new
category and direct-page writes discard these structural fields before saving,
and reads, exports and chatbot evidence omit them from historical sources.
Publishing a Jobs category preserves existing recruitment capacity counts and
leaves the capacity of new derived roles unknown.
Document chunk views, digest metadata, search previews and source downloads apply the same cleanup.
Ordinary prose is preserved. Existing immutable revisions, original uploads,
checksums, embeddings and recovery checkpoints retain their stored identity.

Document uploads on the legacy KB-version lane and brief uploads accept `.txt`,
`.md`, `.markdown`, `.docx` and `.xlsx` only; every accepted format is converted
to plain text before ingest (DOCX/XLSX are parsed from the OOXML container with
the standard library). `.yaml`/`.yml` are refused by name, and PDF is not
supported — there is no extractor.
OOXML extraction rejects archives with more than 1,024 members, more than
64 MiB of declared expanded content, or a parsed XML part larger than 16 MiB. Reads are
bounded independently of archive metadata. XLSX columns must be valid Excel
references within the 16,384-column limit. Extracted XLSX text is bounded to
16 Mi characters; encrypted archives and repeated worksheet references are rejected.

## One-file project training

The project create form and **Nhập từ tệp** action accept one project brief.
The console extracts the supplied facts into the twelve category contracts,
preserves the source file, and uploads the category proposal in the same
request. Missing sections stay marked for review; absence of a salary, age
limit, benefit, or hiring contact never authorizes an invented value.
Plain Vietnamese headings, FAQ question/answer groups, contact hours, job
descriptions, decimal salary ranges, and transport pickup times are retained.
Category Markdown bundles preserve each category's source and pass the same
backend validators as individual edits. Unknown or repeated category blocks
fail validation. Any other plain-text file imports too: when the file is
neither a brief nor a category bundle, the digest LLM maps its content into
the twelve categories — facts only, nothing invented — and the result runs
through the same training pipeline. Conflicting facts and an explicit lack of shuttle service do
not create a fictional route; the source remains available for review.

Once the backend accepts the upload, the ingest worker owns the batch. It
retains extraction results, revisions, and embedding checkpoints privately on
the source. Closing the browser stops observation, not training. The worker
validates the complete proposed category graph together with retained active
categories before publishing a new project snapshot.
Provider calls run outside publication locks. In category authority, one final
transaction publishes all proposed category pointers, evidence, derived Jobs/routes, features,
discovery highlights, and the source's completed receipt. A preparation or
publication failure preserves the previous published snapshot.

Model digest quotes must occur in the uploaded source after Unicode and
whitespace normalization. Empty or ungrounded digests retry, then fall back to
verbatim source units. The digest model-call ceiling limits provider work;
source beyond that ceiling remains searchable through bounded source units.
Original-file extraction and storage run off the web event loop. SQL failures
roll back before saving a retryable failure receipt; provider error bodies are
excluded from that receipt and logs.

The console follows the document's `project_training` receipt and reports
completion only after the worker confirms publication or legacy shadow preparation.
Retry a failed source through its process endpoint or by uploading the same
file again. Unchanged retries reuse valid
prepared work; a newer brief supersedes an interrupted older batch. A manual
category change invalidates the old batch snapshot; reuploading the identical
brief then creates a fresh source intent. Retrying a source-owned category
individually returns a Vietnamese conflict directing the administrator to
retry the whole source. An unchanged completed source is reused while its
published snapshot is still current. Categories absent from a replacement
brief retain their existing knowledge until explicitly reviewed or cleared.

For a Project still using legacy knowledge authority, successful training
prepares shadow categories and defers source-owned features and highlights.
Its completed receipt has `requires_cutover: true`: candidates keep receiving
the existing published data until the administrator explicitly cuts over.
Cutover adopts deferred features only from the current completed source whose
category snapshot still matches, and preserves independent feature edits made
after preparation. Merely opening the feature list does not supersede prepared
features. A successful cutover closes obsolete prepared feature intents rather
than continuing to report that they need cutover; reuploading the same brief
after a real feature edit or supersession creates a fresh source intent.
The browser leaves shadow feature and highlight publication to the backend
transaction. Rollback restores the exact pre-cutover feature rows along with
the legacy card and knowledge pointers.

New projects remain drafts until confirmed knowledge is available and the
administrator completes creation. Activation through the list, editor, or API
requires the latest non-archived training source to be published with a completed
receipt. Existing active projects remain available during replacement training.
For existing projects, successful sibling
categories do not hide an unresolved failure in another category. Historical
document failures superseded by a newer successful document do not keep the
project in an error state.

The category editor reads the confirmed active source when publication changes.
It preserves an open editing buffer, but does not treat queue acceptance as
published content. Failed source reads disable replacement and offer retry;
they cannot turn an unread category into an empty editable form. Discovery card
edits preserve existing eligibility criteria.

## Export saved project knowledge

Administrators can select **Xuất KB** in the project knowledge panel to download
the current saved knowledge as one `.md` file. The action is available in both
single-page and category modes, including the project list's expanded panel,
detail view, and editor. It does not save or replace an open editing buffer.

Single-page exports preserve the saved page text except retired reference fields.
Category exports include the
active published sources in catalog order. Projects awaiting category cutover
export their active legacy KB sources, not prepared shadow categories. Drafts,
pending or failed training, archived documents, and cleared categories are
excluded. If there is no saved knowledge to export, the console shows an error
and creates no file. **Tải mẫu KB** remains a separate blank template.

The file contains current source content; it does not include revision history,
embeddings, credentials, or runtime settings.

## Single-page mode

- The Project has one `.txt` or `.md` page.
- Saving replaces the whole page atomically.
- Saving the first valid page, or a later replacement page, activates an inactive single-page
  Project once the required discovery card exists.
- `knowledge_base_direct_files.raw_text` preserves submitted text after removing retired
  structural reference fields; `normalized_text` and
  `content_sha256` store the deterministic canonical form.
- The complete page and bounded recent Zalo conversation history are supplied to the LLM for
  every focused Project turn, including proactive turns.
- The page never enters chunking, embedding, category ingestion, or RAG retrieval.
- Project list and sidebar readiness for single-page Projects is page-based: one saved page means
  "ready". RAG Projects keep using category readiness.
- The Project still needs a compact discovery card so candidates can find it while exploring.

### Public Google Sheet sync (removed)

Google Sheet sources were fully removed on 2026-10-05: the console surface,
the backend routes, the workers, the daily tick and the two sync-state tables
(migration 0067) are all gone. The section below is kept only as the
historical shape of the removed chain.

Direct-context Projects could attach one additive Google Sheet sync row in
`single_page_external_source_sync_state`. That row is a public-source control
plane, not a replacement for the page itself.

- The admin pastes one public HTTPS Google Sheet URL.
- The backend resolves exactly one `gid` from that URL. A fragment `#gid=...`
  wins over `?gid=...`; missing, invalid, conflicting, or unsafe `gid` values
  are rejected.
- The sheet sync runs either manually from the console (`Xử lý ngay`) or by the
  daily worker tick when `auto_sync_enabled` is on. The tick is pinned to a
  wall-clock time via `KB_SYNC_CRON` (default `0 20 * * *` UTC = 03:00 ICT); a
  mid-day web-container restart no longer pushes the next sync out by 24h.
- The parser accepts the current four-column FAQ sheet shape used by LG
  Display: `STT theo quy trình` | `Thông tin` | `Question` | `Answer`. It also
  tolerates the older 3-column layout.
- The sheet is rendered deterministically into Markdown with the FAQ heading,
  a `## FAQ` section, and `### FAQ: <question>` blocks.
- Sync failure updates the sync-state row, but the prior direct-context page
  stays live. A later successful sync replaces the page atomically.

## Category mode

The Project has twelve independent Markdown categories:

1. Jobs
2. Compensation
3. Requirements
4. Work schedules
5. Benefits
6. Accommodation
7. Meals
8. Transportation
9. Insurance
10. Application
11. Contacts
12. FAQ

Each category uses its code-owned template. A template is a fill-in
questionnaire: every field carries a Vietnamese leading question, so an
administrator who answers all the questions produces a complete, ingest-ready
category (the FAQ template included). The per-category **Tải mẫu** download
action is removed. Administrators can import one Project text file for automatic
classification or use **Sửa nội dung** to edit a category inline; empty categories
start with their questionnaire. An administrator pastes Category Markdown
v1 into the per-category editor — `---` front-matter naming `schema_version`
and `category`, then one `## <list_field>` section of `### record: <stable-id>`
blocks (see `backend/app/services/knowledge/category_markdown.py`). The system
preserves the markdown after removing retired reference fields in `source_markdown`, stores the normalized payload
separately, and computes a deterministic checksum from the canonical JSON
form. Each
revision also carries a durable processing token, lease expiry, bounded attempt count, failure
code, and `quality_result` summary.

Category activation is shadow-only before cutover: the worker validates, embeds, stores indexed
evidence, and advances the category pointer, but live Jobs/routes and retrieval remain legacy until
an explicit Project-wide cutover flips
`category_authority_started`. A failed revision leaves the previous active revision and sibling
categories unchanged. Clearing is an explicit category-only operation. Duplicate worker delivery is
claimed once and cannot create duplicate evidence for the same revision. An expired claim can be
reclaimed after worker death, while a stale worker cannot finalize it.

The Project supplies factory scope, so category files never repeat or reference a factory.
Each category is independently valid and can be prepared or activated before Jobs.
There is no cross-category Job linkage or Jobs-first authoring requirement.

After cutover, Jobs are a derived read model. Every job present in the active Jobs markdown is available; a missing
job is unavailable. There is no administrator-managed job status. Manual Job, FAQ, and feature
mutation endpoints are read-only/conflict paths so Markdown remains the authority. Replacing Jobs also
reapplies every active sibling category to the recreated Job rows. Transportation replaces the
Project's derived bus routes and stops as part of the same category activation.

Category facts apply to the Project. Salary bounds, age bounds, gender, experience,
and meal/accommodation flags enter derived role filters only when every record in
that category supplies the same value. Missing or conflicting values remain unknown
in those filters; every record remains available as KB evidence. A value of zero is
preserved. Requirements and schedule text, benefits and transportation retain all
project records. Jobs are rebuilt before replaying sibling projections as an internal
read-model step, without requiring administrators to order their categories.

Queue submission uses a deterministic RQ job identifier derived from the durable revision. If the
enqueue response is lost, the worker receipt is reconciled before the revision can be marked
failed. An unconfirmed receipt leaves the revision staged, and retrying identical content reuses
that revision and job identifier. A confirmed queue failure marks the staged revision failed and
leaves the previous active pointer unchanged.

## Cutover and rollback

Administrators can use **Chuyển sang kiến thức 12 danh mục** for existing
single-page and legacy RAG projects. Import a complete project brief, wait for
the worker's prepared receipt, and complete the cutover. Missing categories
are cleared only when they have no retained active data and were not written
by that source; reviewed or partially extracted knowledge is preserved.
An empty discovery card does not allow legacy or single-page preparation to
publish category projections early.

The explicit Project-wide cutover requires all twelve categories to be either active or explicitly
cleared. Active revisions must belong to their category and have `ACTIVE`
status; the project must own its KB. The cutover snapshots the previous authority, active KB version, category pointers, and
project-level projection fields before switching retrieval to category evidence.

The admin request bodies use a single `confirmation` field:

- `CLEAR` for category clear.
- `CUTOVER` for Project-wide category authority cutover.
- `ROLLBACK` for restoring the last saved legacy authority snapshot.

Rollback restores the saved category pointers even after later category updates, removes the
category-derived Jobs/routes, and restores the legacy Project card and retrieval authority.

## Candidate conversation scope

A conversation is either:

- `EXPLORE`: no Project is selected. The Agent uses compact discovery cards, active Jobs
  projections, candidate history, and profile context to recommend a small relevant set.
- `FOCUSED`: one Project is selected. Single-page Projects use their complete page; category
  Projects use only Project-scoped active category evidence.

An explicit Project name or alias selects or switches focus. An ambiguous alias asks for
clarification. Explicit requests such as “dự án khác”, “việc khác”, or “xem tất cả” return the
conversation to exploration.

Messenger Page assignments constrain both discovery and focused knowledge
access. Cached routing identities are only hints: the selected or named
Project's active state, current KB, and mode are checked against the database
before loading context. Category-derived Jobs must belong to the current
active Jobs revision.

Generated answers with earlier conversation history are not shared between
candidates. Eligible first-turn answers include private intake context and
messaging provider in a hashed cache scope, so a phone-ready reply cannot skip
the phone request for another candidate. Semantic retrieval entries expire
individually; newer writes do not prolong old results. In-flight retrieval
writes remain in the generation in which they began.

Normal factual answers are composed by the LLM. Empty-table handlers, legacy FAQ bypass results,
and deterministic evidence renderers cannot become the final answer. If generated vacancy prose
conflicts with the authoritative job result, the LLM rewrites it from the verified result; the
common consistent path does not pay for an extra model call.

Recruitment intake prioritizes a valid mobile number as the only mandatory
contact field. Full name is highly recommended, nguyện vọng is useful when
provided, and birth year is optional. Once a mobile number is captured, missing
optional fields do not block project advice or recruiter follow-up. Names and
contact details come from candidate evidence rather than project documents.
An unambiguous candidate-owned phone rejection clears the matching current CRM
phone and reopens collection on later turns; the old value remains in typed
audit evidence. Explicit correction or reconfirmation restores contact. Earlier
deferred extraction cannot resurrect a rejected number or reverse newer
evidence. Missing extractor fields still preserve existing CRM data.
Looking at a project is not evidence of an application: the candidate must
express that intention. Role, location, and salary preferences improve matching
but are not prerequisites for browsing active projects.

Legacy version, document-ingest, reindex, and feature-extraction mutations are rejected once a
Project owns either knowledge mode. They remain read-only only so pre-cutover LG evidence can be
served until an administrator explicitly cuts the Project over to category authority.

The generic template/provenance ingestion framework under `app/services/ingestion/` is dormant: it
has models and tests but is not composed into an active Project API or worker path. It is not the
default ingestion architecture and must not gain a production caller without a separate
architecture decision. Likewise, legacy compatibility code is not removable until production
inventory proves that no stored data or runtime consumer depends on it.

## LG Display migration

Migration `0048_project_owned_knowledge_modes` links the existing sole production RAG knowledge
base to the unambiguous LG Display Project and creates its twelve empty category slots. Migration
`0050_data_ingestion_recovery` adds the durable processing lease fields and the cutover snapshot
columns used by the recovery flow.

Existing LG chunks remain searchable while `category_authority_started` is false. Category
activation and clear prepare independent revisions but do not change retrieval authority. The
explicit cutover requires all twelve categories to be active or deliberately cleared, records the
legacy authority and category pointers, and then switches retrieval to category evidence.
Rollback restores the saved pointers and legacy projections even after later category updates.

Execute the production migration only through the approved deployment workflow, after a fresh
backup and migration dry run.
