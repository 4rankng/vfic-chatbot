# Brief ingestion pipeline — defect-fix round (projects)

Date: 2026-09-30 (Asia/Singapore) · Follows `fullstack-developer-260929-2234-markdown-brief-ingestion.md` and the tailkit retirement wave. Owner directives implemented: the uploaded file is the single source for the whole project knowledge base; admin provides only the project name + file and clicks one button; re-uploads update the knowledge automatically; verify properly in local dev with real LLM calls.

## Root causes found (live symptoms → code)

1. **Nothing filled after upload / bot listed only 2 projects / `Sẵn sàng 0/12`.** Category-revision activation applied the projection only `if project.category_authority_started` — the flag was set solely by the one-shot 12-category cutover, so brief-created projects never projected: `index_card` stayed `{}`, `summary` NULL, job features unwritten. Fix: apply when the project is authoritative **or has no card to protect**, and claim authority on apply; `ProjectService.create` marks new projects authoritative. Legacy pre-built cards stay deferred until cutover (test-pinned).
2. **`Lỗi nạp` on healthy LG-DISPLAY.** `ingest_state` treated any historical FAILED artifact as current state. Recast: in-flight → `ingesting`; else `error` only when the NEWEST artifact is failed; else `ready`/`None`.
3. **Only 2 of 12 categories written ("Cần nhập tay").** `planBriefKnowledge` had builders for jobs+faq only. Now content-driven builders cover all 12 categories from the file's mapped content (typed slots + prose notes); a category is `needsHuman` only when the file has no material or required fields cannot be derived. Validated 4 briefs × 12 categories = 48/48 against the real backend `parse_category_yaml` + pydantic contracts.
4. **`Tài liệu 0`.** The chain never stored the uploaded file. Now every brief (re)ingest uploads the original as a project knowledge document (counted, searchable). The document pipeline skips LLM card/feature/job rebuilds for category-authoritative projects (content-only ingest) so the projection owns the card.
5. **SDS v2 FAQ `409 Category YAML failed validation`.** The newest brief's FAQ section is a markdown pipe table (question col 3, answer col 4); the parser had no pipe-table pairing and emitted entries with empty answers. Extraction now pairs Q/A columns and skips separators; `buildFaqYaml` cannot emit empty question/answer records; partially-answered banks surface in `needsHuman`. New verbatim fixture `fixtures/samsung-sds-dinh-vu-v2.md`.
6. **Acronym role titles killed whole categories.** The retrieval self-test failed records whose title cannot self-retrieve (QA/SMT/UI/MV…, similarity < 0.50) → revision FAILED → card never built. Queries under 5 unicode letters are now "not testable by title alone" and skipped; normal-length queries keep full strictness.
7. **`card.highlights` empty.** Nothing wrote highlights for category-mode projects. The chain now PATCHes `discovery_card: { highlights }` (brief facts) at create and on every re-ingest; `ProjectUpdate` merges into the card (never replaces projection-built keys) and RAG accepts exactly the projection-preserved keys (highlights/eligibility) while still refusing derived keys.
8. **`key_roles` vs `roles` display gap.** `ProjectShow` read only legacy `key_roles`; projection-built cards write `roles`. Rendering now unions both shapes.

## Flow rulings implemented

- Create: only the project name requires input + the file; slug derived, aliases/roles auto-filled and editable, no mode control (always category mode), no confirmation dialogs on the brief path (revisions archive history), one create click.
- Re-upload ("Nhập từ tệp") runs the complete chain every time (fresh parse → full 12-category write set), stores the new file, re-projects the card; no prompts.

## Verification (local dev, real OpenRouter embeddings)

`make dev` stack (uvicorn + RQ `ingest` worker + Zalo mock + vite) with `OPENROUTER_API_KEY` wired from the owner-provided key; three real briefs (AMTRAN, 4P ELECTRONICS, Samsung SDS v2) driven end-to-end through create → 12 category writes → document upload → worker processing:

| brief | writes | active | card (summary/roles/location/highlights) | docs | failures |
|---|---|---|---|---|---|
| Amtran | 12/12 | ✓ | ✓ / 7 / ✓ / 4 | 1 | 0 |
| 4P | 12/12 | ✓ | ✓ / 6 / ✓ / 6 | 1 | 0 |
| SDS v2 | 12/12 | ✓ | ✓ / 8 / ✓ / 6 | 1 | 0 |

Gates: backend 91 focused + 24 integration passed (incl. new projection/self-test/doc-storage tests); frontend typecheck 0 errors, 793/793 unit tests; domain fixtures 81/81; backend contract harness 48/48.

## Notes

- pi-lens "SQL injection" findings in `services/project/{service,repository}.py` are false positives: all flagged sites are static SQL with bound `ANY(:ids)` parameters (verified: no string-built SQL in those files).
- The OpenRouter key value was echoed once by a diagnostic grep into the session transcript; rotation advised if the transcript leaves the owner's machine.
