# Project knowledge workflow

Knowledge is owned by a Project, such as LG Display, Samsung, or PQC. A Project
chooses exactly one mode when it is created. The mode cannot be changed after
content exists.

## Single-page mode

- The Project has one `.txt` or `.md` page.
- Saving replaces the whole existing page.
- The complete page and bounded recent Zalo conversation history are supplied to
  the LLM for every focused Project turn, including proactive turns.
- The page never enters chunking, embedding, category ingestion, or RAG retrieval.
- The Project must also have a compact discovery card so candidates can find it
  while exploring across Projects.

## Category mode

The Project has twelve independent YAML categories:

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

Each category uses its code-owned template. An administrator may paste YAML or
upload a `.yaml`/`.yml` file. The system validates and embeds a staged revision,
then atomically advances that category's active pointer. A failed revision leaves
the previous active revision and all sibling categories unchanged. Clearing is an
explicit category-only operation. Duplicate worker delivery is claimed once and
cannot create duplicate evidence for the same revision.

The Project supplies factory scope, so category files never repeat or reference a
factory. Cross-category `job_ids` refer only to stable IDs in the same Project's
Jobs category.

Jobs are a derived read model. Every job present in the active Jobs YAML is
available; a missing job is unavailable. There is no administrator-managed job
status. Manual Job, FAQ, and feature mutation endpoints are read-only/conflict
paths so YAML remains the authority. Replacing Jobs also reapplies every active
sibling category to the recreated Job rows. Transportation replaces the Project's
derived bus routes and stops as part of the same category activation.

## Candidate conversation scope

A conversation is either:

- `EXPLORE`: no Project is selected. The Agent uses compact discovery cards,
  active Jobs projections, candidate history, and profile context to recommend a
  small relevant set.
- `FOCUSED`: one Project is selected. Single-page Projects use their complete
  page; category Projects use only Project-scoped active category evidence.

An explicit Project name or alias selects or switches focus. An ambiguous alias
asks for clarification. Explicit requests such as “dự án khác”, “việc khác”, or
“xem tất cả” return the conversation to exploration.

Normal factual answers are composed by the LLM. Empty-table handlers, legacy FAQ
bypass results, and deterministic evidence renderers cannot become the final
answer. If generated vacancy prose conflicts with the authoritative job result,
the LLM rewrites it from the verified result; the common consistent path does not
pay for an extra model call.

Legacy version, document-ingest, reindex, and feature-extraction mutations are
rejected once a Project owns either knowledge mode. They remain read-only only so
pre-cutover LG evidence can be served until the first category activation.

## LG Display migration

Migration `0048_project_owned_knowledge_modes` links the existing sole production
RAG knowledge base to the unambiguous LG Display Project and creates its twelve
empty category slots. Existing LG chunks remain searchable while
`category_authority_started` is false. The first deliberate category activation
or clear switches the Project to category authority; legacy chunks do not reappear
after that cutover.

Execute the production migration only through the approved deployment workflow,
after a fresh backup and migration dry run.
