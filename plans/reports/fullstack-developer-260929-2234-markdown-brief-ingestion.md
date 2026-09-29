# Markdown brief ingestion (projects) — completion report

Date: 2026-09-29/30 (Asia/Singapore) · Lane: brief-md-ingest · Owner rulings of 29 Sep implemented.

## Controller amendments (2026-09-30, shipped after the lane report below)

The lane report is kept as written; two pre-commit audit gaps and one ruling
amendment changed the shipped reality as follows.

1. **Text files are accepted; markdown is the focus format.** The later owner
   ruling ("user can upload any text file, pipeline handles all, focus
   markdown") supersedes "Markdown is the only upload format" and the shipped
   `.md`-only rejection wall. `ProjectBriefImport` and `ProjectKnowledgePanel`
   now accept any text file (`.md`/`.txt`/`.markdown`/`text/*`), reject only
   clearly non-text shapes with "Chỉ chấp nhận tệp văn bản.", and keep the byte
   caps. Markdown copy positions `.md` as the recommended format. The parser
   was already shape-agnostic and is unchanged.
2. **Agent-facing proof landed.** `backend/tests/test_brief_fixture_ingestion.py`
   drives the real create + jobs-revision + projection chain with the Amran
   fixture's front-matter facts and asserts they land in `projects.index_card`
   (roles/location/highlights) and `Project.name`/`aliases`, then asserts
   `active_projects_index` (the bot's active-project index) renders name, alias,
   roles, location and highlights. The route-snapshot comment in
   `backend/tests/test_runtime_surface_inventory.py` was reworded to match.

## What was ruled and what shipped

1. **Markdown is the only upload format for project briefs.** YAML file support removed.
2. **Real recruiter briefs ingest properly.** Three real fixtures copied verbatim into the repo and asserted as the ingestion contract.
3. **No fabrication.** Template instructions and sample material are treated as no-data ("cần nhập tay"); nothing reports ready unless the backend accepted the revision.

## Fixture reality (important deviation from the scouting notes)

The three `/Users/dev/Downloads/*.md` files **changed on disk during this task** (Amtran: 8 992 B at 23:05 → 15 598 B at 23:22). Two vintages were seen:

- Early bytes: clean label-line briefs ("PHẦN I/II", `**Label:**` bullets, `**Câu hỏi người lao động thường hỏi:**` markers), Samsung SDS carrying sample material as `> **Nội dung mẫu tham khảo:**` blockquotes.
- Final bytes (copied into the repo): YAML-frontmatter documents (`project_name`, `target_positions`, `base_salary`…) with `## N. Section` headings and per-section `- **Hỏi:** … / - **Trả lời:** …` FAQ pairs. No HTML tables, no template placeholders, no example columns remain in these bytes.

The parser upgrade therefore covers **both generations plus the ruled traps** (HTML tables with example columns, placeholder cells, sample markers) so any of the shapes can arrive. The golden YAML export `tuyen_dung_amtran_vsip_hai_phong.yaml` no longer exists anywhere on disk (searched Downloads/Desktop/Documents + mdfind); golden assertions were built from the enumerated facts in the task instead.

## Parser design (domain/project-brief-ingest.ts)

Everything runs before sectioning; `rawText` stays verbatim. All passes are linear, bounded regexes (semgrep-safe; no nested quantifiers).

- **HTML table unwrap** (`unwrapHtmlTables`): `<table>…</table>` → pipe rows. Cells unwrapped (`<br>`/block tags → line breaks, `<li>` → `- `, entities decoded, bounded tag strip). Example columns: a header cell folding to "ví dụ mẫu"/"mẫu tham khảo" drops its column and everything after it in every row — generalized from marker text, not file names.
- **Sample blockquotes** (`dropExampleBlocks`): a `>`-quote run whose first content line carries an example marker is dropped whole.
- **Placeholder cells** (`isPlaceholderValue`): the intake form's instruction sentences ("Tên gọi phổ biến người lao động hay hỏi", "Giới thiệu ngắn gọn … về công việc") fold-match a pattern list and never become values — the field stays empty and lands in needsHuman. Applied to both the table reader and the label-line reader.
- **Frontmatter** (`parseFrontmatter`): the `---`-fenced header wins for `project_name`/`workplace_location`/`target_positions` (structured header beats prose interpretation); everything else comes from the body.
- **Q&A markers**: variants "Câu hỏi (người lao động) thường hỏi/gặp", "Thông tin phản hồi / tư vấn / tư vấn dự án …", and the new inline `- **Hỏi:** … / - **Trả lời:** …` pairs with payload extraction. Short markers are anchored at line start — an unanchored `hoi:` read "phản **hỏi**:" as a question marker, and unanchored `giai dap` matched the prose "giải đáp các thắc mắc" inside a contacts bullet (both bugs found by test and fixed).
- **Depth-aware inheritance**: `####` sub-sections inherit the nearest shallower mapped section's category and contribute their own title as content ("Lương cơ bản: 6.300.000 VNĐ / tháng" IS the salary fact). Question-titled headings (`#### ❓ …?`) become FAQ entries (Chủ đề tags dropped, "Câu trả lời chuẩn:" stripped).
- **Label reading**: bare labels may carry descriptive tails when colon-terminated ("Các điểm nổi bật thu hút người lao động:"); bare AND colon-stub inline labels collect a bullet run (≤8 lines) as their value.
- **Structural containers** (masthead, "PHIẾU…", "PHẦN…", "Thông tin tổng quan…", "Ngân hàng câu hỏi…") are never reported as unmapped noise.
- Category heading patterns extended for the real sheets: jobs ("Vị trí công việc", "Mô tả công việc"), work_schedules ("Thời gian làm việc", "Ca kíp" — and compensation lost the bare "tăng ca" so a schedule section keeps its own heading), application ("Quy trình nhận việc/tuyển dụng", "Thủ tục nghỉ việc"), contacts ("liên hệ" bare), aliases ("Tên doanh nghiệp tiếp nhận"). Overrides added: meals→transportation (shuttle answers), insurance→benefits (environment/welfare bullets).

## Per-file ingestion results

- **Amtran** (golden): name "Dự án Amtran Vsip Hải Phòng", aliases ["Công ty Amtran (AmTRAN Technology)"], location "Hải Phòng" (address "Khu công nghiệp VSIP Thủy Nguyên, TP. Hải Phòng"), roles = the 7 `target_positions`, **all 12 knowledge categories genuinely filled, missingCategories = [], unmappedSections = []**. Golden facts asserted: job "Nhân viên lắp ráp cơ khí & linh kiện điện tử"; salary 6.300.000; the 8 allowances (700k/500k/400k/100k/1.000k/200k–1.000k/thâm niên max 1.000k/50k đêm); shifts 08:00–17:00 (trưa 12:00–13:00) and 20:00–05:00; OT min 1h + 30-min meal counts as 1h; free canteen; no KTX; no shuttle but 500k xăng xe; BHXH at 6.300.000; smock; Đăng ký→Phỏng vấn→Đi làm + document lists; contact Ngọc Thảo 0963019380; age 18–37 (above considered); no diploma/experience; tattoos. ≥15 paired FAQ entries.
- **4P Electronics**: frontmatter name/address/roles; aliases ["4P Electronics", "Công ty 4P"]; salary 6.200.000–6.300.000; chuyên cần 400k, đứng máy 600k–1.300k, đi lại 300k; meals free; no KTX; no shuttle + 300k; BHXH from month 2; contacts Admin Phượng. The two template-placeholder cells of the previous vintage would fold-match the placeholder list (guarded; synthetic-tested).
- **Samsung SDS**: warehouse roles verbatim (kho mát 15 °C / kho lạnh 5 °C / xuất hàng); 300.000/ca 8h; shifts 09:00–18:00 / 20:00–04:00; meals free + 30k substitute; shuttle Kiến An/Aeon/Go!; BHXH month 3; three contacts; ≥12 FAQ entries including the Q&A bank. **No LG Display/Rorze sample material anywhere in the parsed knowledge** (asserted).

## What was removed

- **Backend**: `POST /knowledge/projects/{project_id}/categories/{category_key}/upload` (the 409-on-.md route) deleted from `backend/app/api/projects.py` together with the now-unused `File`/`UploadFile` imports. It had **no direct backend test**; the route-count + inventory-digest snapshots in `backend/tests/test_runtime_surface_inventory.py` were updated (`projects: 28 → 27`, new sha `1058d665…70637`). The per-category PUT (`source_yaml` JSON body) is untouched — YAML as internal request bodies is plumbing, not a file format.
- **Frontend**: `uploadCategory` removed from port → operations → HTTP adapter → service (`uploadProjectKnowledgeCategory`) → catalog hook → `useCategoryDraft.upload` → the "Tải file YAML" button in `CategoryEditor.tsx` (placeholder copy reworded). The multipart test in the adapter test and the catalog hook's upload-trigger lifecycle tests were re-anchored on `replaceCategory`.
- **Create flow**: `ProjectBriefImport` accepts `.md` only; non-markdown picks get "Chỉ chấp nhận tệp markdown (.md)."; copy no longer mentions .txt.
- **Panel**: `ProjectKnowledgePanel` (RAG side) gained `BriefIngestSection` — "Nhập từ phiếu .md" — reusing `parseProjectBrief` + `planBriefKnowledge` + the create flow's `useProjectIngest` chain (jobs-first writes, each write awaited to ACTIVE/FAILED via the catalog poll, confirm-before-replace, per-category progress, "Cần nhập tay: …" from `plan.needsHuman`). Note: `planBriefKnowledge` today writes only the categories its builders can express honestly (jobs + faq) and names the other ten as needsHuman — reusing the create flow's semantics exactly rather than inventing YAML for ten schema families.

## Verification evidence

Frontend (Vitest 4.1.11, browser project):

- `npx vitest run --project app src/components/atomic-crm/projects/domain/` → **5 files / 59 tests passed** (parser 20, new fixtures 13, yaml/policy/polling 26).
- `npx vitest run --project app src/components/atomic-crm/projects/` → **16 files / 141 tests passed** (incl. ProjectCreate .md flow, panel 14).
- `npx tsc --noEmit -p tsconfig.app.json` → **0 errors in projects/** (15 remaining errors are pre-existing in `kit/`/`dashboard/` from another lane's in-flight work).
- `npx prettier --check` clean on all touched files; `npx eslint` clean (one `no-useless-escape` found and fixed).

Backend:

- `pytest tests/test_knowledge_category_contracts.py tests/test_project_category_edit_permissions.py tests/test_project_knowledge_boundaries.py tests/test_project_service.py tests/test_category_units_rendering.py -p no:randomly -q` → **87 passed**.
- `pytest tests/test_category_projections_sibling_batch.py tests/test_category_worker.py tests/test_backfill_project_categories_script.py tests/test_legacy_category_backfill.py tests/test_runtime_surface_inventory.py -p no:randomly -q` → **20 passed** after the snapshot update.
- `python -c "import app.api.projects"` → clean.

## For the controller before committing

- **`npm run registry:gen` must run** (registry.json stores file contents; I edited published app files and am forbidden to touch registry.json). Pre-commit runs it, but regenerate deliberately and review the diff.
- New files to add: `frontend/src/components/atomic-crm/projects/domain/fixtures/{amtran-vsip-hai-phong,four-p-electronics,samsung-sds-kho}.md` (verbatim copies; Downloads originals untouched) and `…/domain/project-brief-ingest.fixtures.test.ts`.
- The 15 pre-existing typecheck errors outside projects/ and the layout/kit churn belong to other lanes.

Status: DONE
Summary: Markdown-only brief ruling shipped end to end — yaml upload route + affordance removed, real-fixture golden ingestion proven (Amtran fully carried, placeholders/samples never ingested), panel ingests briefs via the awaited revision pipeline with cần-nhập-tay reporting; all suites green.
Concerns: The Downloads fixtures regenerated mid-task (two vintages seen); the golden YAML export named in the brief no longer exists, so golden assertions came from the task's enumerated facts. `npm run registry:gen` is left to the controller.
