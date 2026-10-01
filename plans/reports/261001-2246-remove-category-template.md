# Remove the per-category template download

Removed the exact **Tải mẫu** action from every category editor, along with its Download icon, browser attachment callback, template filename state and download-only public draft members. The empty-state guidance now points to importing a Project text file; textarea placeholders describe inline editing rather than an unavailable download. Internal questionnaire loading still seeds a new inline edit. **Tải mẫu KB đầy đủ** and **Xuất KB** are separate Project actions and remain available.

Cause: the category editor exposed a separate legacy-shaped category download beside the intended Project text-file import flow. Removing only the visible button would leave unused download logic and misleading instructions, so the change removes those together. Backend contracts, stored history and API endpoints are unchanged. Previous authorized audit changes are preserved.

Changed files this round: CategoryEditor.tsx, use-category-draft.ts, ProjectKnowledgePanel.test.tsx, docs/guides/knowledge-base-workflow.md, and this report/completion record. Independent read-only review confirmed that no downloadTemplate/templateFilename/draft.template callers remain. Pre-existing YAML filenames in legacy test fixtures are not runtime download paths and were preserved.

Validation on the final source:

- 45 focused Chromium component tests passed, covering published and empty categories without the exact button, inline edit seeding, source refresh/cancel/save guards and Project downloads.
- 896 frontend tests across 118 files passed.
- Frontend app TypeScript and scoped ESLint passed.
- Production build and built-browser smoke passed.
- Doc routing (32 paths, 4 targets and 4 documents) and git diff whitespace checks passed.

Logs: /tmp/vfic-remove-category-template-{tests,frontend-all,types,lint,build,smoke}.log. Backend checks were not rerun because backend code and contracts did not change; earlier backend/PostgreSQL evidence is preserved in the preceding report. No live providers or production environment were used.

Portable deliverables: plans/exports/2026-10-01-remove-category-template.patch is the full cumulative diff against main 35d970689cbb092e4f9100f1e60305c9bd7505ed. The incremental patch of the same stem applies after 2026-10-01-simplified-jobs-kb.patch (SHA256 26a4c5ed98772ea74768577e9cc62adc7fce2d7bda3193dcb1d335b388190621). Both patch paths are applied in fresh trees, checked for exact file bytes/executable modes, and reverse-checked. Final manifests/README contain checksums and apply evidence. Prior patches, HEAD, real Git index and working status remain unchanged.

No branch, commit, push, PR, merge, deployment, migration or dependency change. All source edits remain unstaged and uncommitted.
