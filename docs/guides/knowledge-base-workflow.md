# Project knowledge workflow

Knowledge is owned by a Project, such as LG Display, Samsung, or PQC. A Project chooses one
mode when it is created; the mode does not change after content exists.

## Current ingestion lanes

| Lane | Raw source preserved | Canonical representation | Activation / retrieval |
|---|---|---|---|
| Direct context | Exact page text | Deterministically normalized text plus checksum | Atomic whole-page replace; the focused Project reads the full page |
| Project categories | Exact Markdown per immutable revision | Strict typed payload plus deterministic checksum | Shadow-only prepare first, then explicit Project-wide cutover to category authority |
| Legacy KB versions | Uploaded document/version | Canonical Markdown is deterministic; free-form input uses the compatibility digest pipeline | Active legacy version remains readable only before category cutover |

The lifecycle vocabulary is shared across lanes:

- **Raw source** is the exact administrator input.
- **Normalized representation** is meaning-preserving deterministic text or structured data.
- A **validated revision** has passed schema and reference checks.
- A **projection** is a derived chunk, Job, route, or stop.
- The **active pointer** selects authoritative content.
- A **derived read model** can always be rebuilt from that authority.

Document uploads on the legacy KB-version lane and brief uploads accept `.txt`,
`.md`, `.markdown`, `.docx` and `.xlsx` only; every accepted format is converted
to plain text before ingest (DOCX/XLSX are parsed from the OOXML container with
the standard library). `.yaml`/`.yml` are refused by name, and PDF is not
supported — there is no extractor.

## One-file project training

The project create form and **Nhập từ tệp** action accept one project brief.
The console extracts the supplied facts into the twelve category contracts,
preserves the source file, and uploads the category proposal in the same
request. Missing sections stay marked for review; absence of a salary, age
limit, benefit, or hiring contact never authorizes an invented value.

Once the backend accepts the upload, the ingest worker owns the batch. It
processes Jobs before categories that reference job IDs and saves category
revision checkpoints on the retained source document. Closing the browser
stops observation, not training. The console follows the document's
`project_training` receipt and reports completion only after the worker
confirms the proposed categories. A category or feature extraction failure is
visible and the retained source can be retried through the document process
endpoint or by uploading the same file again. Each category cutover is atomic;
a batch may publish earlier categories before a later category fails. Its
receipt preserves that partial progress for retry. The previous active
revision of a failed replacement remains available. An unchanged completed
source is reused, while a different newer brief supersedes an interrupted
older batch. Categories absent from a replacement brief keep their existing
knowledge until the administrator explicitly reviews or clears them.

New projects remain drafts until confirmed knowledge is available and the
administrator completes creation. Activation through the list, editor, or API
requires the latest non-archived training source to be published with a completed
receipt. Existing active projects remain available during replacement training.
For existing projects, successful sibling
categories do not hide an unresolved failure in another category. Historical
document failures superseded by a newer successful document do not keep the
project in an error state.

## Single-page mode

- The Project has one `.txt` or `.md` page.
- Saving replaces the whole page atomically.
- Saving the first valid page, or a later replacement page, activates an inactive single-page
  Project once the required discovery card exists.
- `knowledge_base_direct_files.raw_text` preserves the original text; `normalized_text` and
  `content_sha256` store the deterministic canonical form.
- The complete page and bounded recent Zalo conversation history are supplied to the LLM for
  every focused Project turn, including proactive turns.
- The page never enters chunking, embedding, category ingestion, or RAG retrieval.
- Project list and sidebar readiness for single-page Projects is page-based: one saved page means
  "ready". RAG Projects keep using category readiness.
- The Project still needs a compact discovery card so candidates can find it while exploring.

### Public Google Sheet sync

Direct-context Projects can attach one additive Google Sheet sync row in
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
category (the FAQ template included). An administrator pastes Category Markdown
v1 into the per-category editor — `---` front-matter naming `schema_version`
and `category`, then one `## <list_field>` section of `### record: <stable-id>`
blocks (see `backend/app/services/knowledge/category_markdown.py`). The system
preserves the raw markdown in `source_markdown`, stores the normalized payload
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
Cross-category `job_ids` refer only to stable IDs in the same Project's Jobs category.

After cutover, Jobs are a derived read model. Every job present in the active Jobs markdown is available; a missing
job is unavailable. There is no administrator-managed job status. Manual Job, FAQ, and feature
mutation endpoints are read-only/conflict paths so Markdown remains the authority. Replacing Jobs also
reapplies every active sibling category to the recreated Job rows. Transportation replaces the
Project's derived bus routes and stops as part of the same category activation.

Queue submission uses a deterministic RQ job identifier derived from the durable revision. If the
enqueue response is lost, the worker receipt is reconciled before the revision can be marked
failed. An unconfirmed receipt leaves the revision staged, and retrying identical content reuses
that revision and job identifier. A confirmed queue failure marks the staged revision failed and
leaves the previous active pointer unchanged.

## Cutover and rollback

The explicit Project-wide cutover requires all twelve categories to be either active or explicitly
cleared. The cutover snapshots the previous authority, active KB version, category pointers, and
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

Normal factual answers are composed by the LLM. Empty-table handlers, legacy FAQ bypass results,
and deterministic evidence renderers cannot become the final answer. If generated vacancy prose
conflicts with the authoritative job result, the LLM rewrites it from the verified result; the
common consistent path does not pay for an extra model call.

Recruitment intake prioritizes a valid mobile number as the only mandatory
contact field. Full name is highly recommended, nguyện vọng is useful when
provided, and birth year is optional. Once a mobile number is captured, missing
optional fields do not block project advice or recruiter follow-up. Names and
contact details come from candidate evidence rather than project documents.
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
