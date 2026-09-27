"""Wave-3 tickets: the repowise health/dead-code sweep of 2026-09-27 (HEAD `d2e8889f`).

One read-only pass with repowise MCP tools (`get_health` production-scope dashboard,
`get_dead_code` at min_confidence 0.5, plus the stored performance plan for
`perf2_30eeea1fc26b17caa2a2`), deduped against the wave-1/2 board. Already-carded
subjects were skipped (runner.py ARCH-20, KnowledgeCategoryService ARCH-23,
graph/clients.py ARCH-05); change-entropy-only files and skill assets were not
carded (see the README wave-3 section). Ids continue each area sequence
(allocated once, never renumbered; TEST-22 was consumed by its retirement).
Every claim is anchored to a `path:line` read at this HEAD; the dead-code set was
grep-verified at zero references in the working tree on 2026-09-27 because the
TypeScript call-edge basis runs 44% guessed.
"""

AUDIT_DATE = "20260927"
AUDIT_HEAD = "d2e8889f"

TICKETS: list[dict] = [
    # -------------------------------------------------------------- ARCH --
    dict(
        id="ARCH-29",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Split backend/scripts/seed_dev.py: 2102-line seed script is the repo's #2 churn-weighted deficit",
        sev="medium",
        area="architecture",
        labels=["god-module", "dev-tooling"],
        effort="M",
        problem=(
            "The repowise production-scope health dashboard ranks seed_dev.py second only to "
            "graph/runner.py in weighted health deficit (8,886 points, 3.5% of the repo's total "
            "gap to the score-8 target, file score 3.41/10). The whole dev fixture factory lives "
            "in one 2102-line script: 23 top-level make_* functions spanning users, projects, "
            "companies, personas, jobs, worker features, leads, conversations, messages/bot runs, "
            "performance metrics, knowledge, and audit events, plus truncation and the seed() "
            "entrypoint. Two functions are brain-methods in their own right: "
            "make_messages_and_bot_runs spans roughly 550 lines (:1060-1613) and "
            "seed_performance_metrics (:1613) reaches CCN 41 at 4 levels of nesting."
        ),
        evidence=[
            "backend/scripts/seed_dev.py — 2102 lines, 23 top-level functions, file score 3.41/10, weighted deficit 8,886 (repowise get_health production scope, #2 behind runner.py)",
            "backend/scripts/seed_dev.py:1060-1613 — make_messages_and_bot_runs: ~550-line function building the conversation/bot-run message corpus",
            "backend/scripts/seed_dev.py:1613-1735 — seed_performance_metrics: CCN 41, nesting depth 4 (repowise nested_complexity biomarker)",
            "backend/scripts/seed_dev.py:1955 — seed() entrypoint orchestrates all fixture domains inline",
        ],
        impact=(
            "Any fixture change edits a file every lane has to read; the script has no test file "
            "of its own, so seed regressions surface only when a dev environment refuses to boot. "
            "Its deficit rank means it is one of the 20 files holding half the repo's health gap."
        ),
        fix=(
            "Split into a backend/scripts/seed/ package along the existing make_* seams (one "
            "module per fixture domain, shared helpers in a common module), keeping "
            "scripts/seed_dev.py as a thin entrypoint that imports seed(). No behavior change: "
            "the same fixtures, same IDs, same output — verify by diffing a seeded database "
            "before/after."
        ),
        notes="Dev tooling, not the production hot path — priority comes from churn-weighted deficit, not runtime risk.",
    ),
    dict(
        id="ARCH-30",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Delete the five zero-reference files and exports repowise flags at high confidence",
        sev="low",
        area="architecture",
        labels=["dead-code", "frontend"],
        effort="S",
        problem=(
            "repowise get_dead_code (min_confidence 0.5) returns exactly five product-code "
            "findings at high confidence, all safe-to-delete and all still present at HEAD: two "
            "unreachable admin components untouched since June, one unreachable lib type module, "
            "and two unused domain exports. All five were grep-re-verified at zero references "
            "outside their defining files before carding, because the TypeScript call-edge "
            "resolution basis runs 44% guessed."
        ),
        evidence=[
            "frontend/src/components/admin/confirm.tsx — unreachable (in_degree=0), 20 lines, last touched 2026-06-22 (97 days)",
            "frontend/src/components/admin/icon-button-with-tooltip.tsx — unreachable (in_degree=0), 20 lines, last touched 2026-06-22",
            "frontend/src/lib/field.type.ts — unreachable (in_degree=0), 10 lines",
            "frontend/src/components/atomic-crm/personas/domain/personaMarkdown.ts:155-157 — export hasPersonaFollowupRules has no importers",
            "frontend/src/components/atomic-crm/reporting/domain/performanceDiagnostics.ts:134-135 — export getEndToEndMetric has no importers",
            "grep verification 2026-09-27: hasPersonaFollowupRules and getEndToEndMetric appear in no file outside their defining modules",
        ],
        impact=(
            "Dead frontend surface that linters and tsc pass over: readers and future refactors "
            "must reason about five files nobody can reach, and the two admin orphans are old "
            "enough to predate the current atomic-crm layout."
        ),
        fix=(
            "Delete the three files and both exports, then run npm run typecheck and the vitest "
            "suite — their passing is the final reference check. If any has a hidden runtime "
            "loader (none is expected: none is named in config or manifest files), restore and "
            "record why in this card."
        ),
    ),
    dict(
        id="ARCH-31",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Flatten profile_enrichment.enrich_messenger_user: CCN 42 across 5 nesting levels",
        sev="medium",
        area="architecture",
        labels=["nested-complexity", "backend"],
        effort="M",
        problem=(
            "profile_enrichment.py is one of the worst-maintained production services "
            "(maintainability 1.7, file score 1.85/10, weighted deficit 3,001). Its core "
            "enrich_messenger_user method (:424) reaches CCN 42 across 5 nesting levels: the "
            "messenger profile fetch, field mapping, and persistence decisions are stacked in "
            "nested conditionals instead of guard clauses."
        ),
        evidence=[
            "backend/app/services/profile_enrichment.py — 581 lines, maintainability 1.7, score 1.85/10 (repowise get_health production scope)",
            "backend/app/services/profile_enrichment.py:424 — enrich_messenger_user: CCN 42, nesting depth 5 (repowise nested_complexity biomarker)",
        ],
        impact=(
            "The enrichment path runs on every inbound messenger contact; each new profile field "
            "or provider quirk has to be threaded through the same nested ladder, and the depth "
            "makes the failure branches effectively untestable in isolation."
        ),
        fix=(
            "Convert the nesting to guard clauses and extract the per-field mapping into small "
            "pure helpers. Keep REL-05's gender-blank fix (already QA_TESTED in this file) intact "
            "— its regression test must keep passing untouched."
        ),
        notes="REL-05 (lead gender TOCTOU) landed in this file; coordinate the refactor with its regression test.",
    ),
    dict(
        id="ARCH-32",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Flatten zalo_bot_service._split_long_plain_text: 5-level nesting in the channel's message splitter",
        sev="low",
        area="architecture",
        labels=["nested-complexity", "zalo"],
        effort="S",
        problem=(
            "zalo_bot_service.py (666 lines, file score 2.35/10) splits outbound Zalo messages "
            "through _split_long_plain_text (:322), which nests 5 levels deep while resolving "
            "the length-vs-chunk tradeoff. The splitter is shared by every text reply the Zalo "
            "channel sends."
        ),
        evidence=[
            "backend/app/services/zalo_bot_service.py — 666 lines, score 2.35/10 (repowise get_health production scope)",
            "backend/app/services/zalo_bot_service.py:322 — _split_long_plain_text: nesting depth 5 (repowise nested_complexity biomarker), called at :439",
        ],
        impact=(
            "Every Zalo reply passes through the ladder; a boundary mistake here silently "
            "truncates or over-splits customer-visible messages, and the nesting makes the "
            "boundary cases hard to see let alone test."
        ),
        fix=(
            "Rewrite with guard clauses (return the unsplit text early, then one loop over "
            "paragraph/sentence/word fallbacks) and extract the deepest branch into a named "
            "helper. Add boundary tests at the exact chunk limits before touching it."
        ),
    ),
    dict(
        id="FE-27",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Extract PersonaStudioOverview: a 310-line CCN-27 brain method inside PersonaList.tsx",
        sev="medium",
        area="frontend",
        labels=["brain-method", "personas"],
        effort="M",
        problem=(
            "PersonaList.tsx (782 lines) defines PersonaStudioOverview (:215) as a single "
            "roughly 310-line component with CCN 27 — repowise's brain-method biomarker for the "
            "file — and renders it once at :748. The component carries the studio overview's "
            "layout, summary metrics, and list composition in one body."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/personas/PersonaList.tsx — 782 lines, score 3.4/10 (repowise get_health production scope)",
            "frontend/src/components/atomic-crm/personas/PersonaList.tsx:215 — PersonaStudioOverview: ~310 lines, CCN 27, defined inline",
            "frontend/src/components/atomic-crm/personas/PersonaList.tsx:748 — the single render site",
            "repowise graph: PersonaList.tsx reaches 49 dependents (transitive; 4 direct importers by grep)",
        ],
        impact=(
            "The studio overview is the personas landing surface; every addition lands in the "
            "same 310-line body, and the file's 49-dependency reach means review noise spreads "
            "across the personas area."
        ),
        fix=(
            "Extract PersonaStudioOverview (and any sub-blocks it already names) into "
            "personas/presentation/ per the house domain/application/presentation layout, "
            "keeping props narrow and the single render site in PersonaList. The existing "
            "PersonaList.mobile-layout.test.tsx must pass unchanged."
        ),
    ),
    dict(
        id="FE-28",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Decompose ChatThread: a CCN-92 component in an 882-line presentation module",
        sev="medium",
        area="frontend",
        labels=["function-hotspot", "conversations"],
        effort="M",
        problem=(
            "ChatThread.tsx (882 lines, 765 nloc) is the conversation thread's presentation "
            "module, and its ChatThread component (:331) alone reaches CCN 92 — the highest "
            "cyclomatic complexity of any frontend component in the repowise production scan — "
            "while the file churns at the repo p80 for recent commits. Message grouping, bubble "
            "variants, status rails, and composer interplay all live in the one body."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx — 882 lines, score 4.25/10 (repowise get_health production scope)",
            "frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:331 — export const ChatThread: CCN 92, nesting 3",
            "repowise function-hotspot biomarker: modified across 3 recent commits (repo p80 = 3)",
        ],
        impact=(
            "The inbox's most-edited surface is also its most complex function; every thread "
            "feature pays re-read cost, and regressions concentrate where review attention is "
            "thinnest."
        ),
        fix=(
            "Extract message-grouping and bubble-variant sub-components beside the module per "
            "the FE-13 conversations layout, memoizing on real inputs (the FE-05 view-model "
            "pattern). While splitting, route data access through an application-layer port so "
            "the file stops importing providers/rest/dataProvider directly — that edge is the "
            "recorded QA gate on FE-08."
        ),
        notes="FE-05 and FE-08 both touched this file's neighborhood; land after those are QA-closed to avoid rework.",
    ),
    dict(
        id="FE-29",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Split PerformancePage.tsx: 1002 lines holding ~15 inline components",
        sev="medium",
        area="frontend",
        labels=["god-module", "reporting"],
        effort="M",
        problem=(
            "PerformancePage.tsx is a 1002-line single module (980 nloc, maintainability 4.0) "
            "defining the whole performance dashboard inline: Status, Metric, PerformanceLoading, "
            "PerformanceError, AttentionQueue, StageMatrix, AdapterComparison, MobileDiagnostics, "
            "TurnDetail, MobileTurnCard, SlowestTurns, SupportingStats, and PerformanceNoActivity "
            "are all file-local components stacked in one file. It is also a change-entropy "
            "hotspot (top 3.4% for scattered churn), so the inline stack keeps absorbing edits."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/performance/PerformancePage.tsx — 1002 lines, 980 nloc, maintainability 4.0, weighted deficit 5,390 (repowise get_health production scope)",
            "frontend/src/components/atomic-crm/performance/PerformancePage.tsx:52-:796 — thirteen file-local components (Status :52, Metric :69, PerformanceLoading :92, PerformanceError :103, AttentionQueue :137, StageMatrix :242, AdapterComparison :350, MobileDiagnostics :414, TurnDetail :472, MobileTurnCard :515, SlowestTurns :594, SupportingStats :741, PerformanceNoActivity :796)",
            "frontend/src/components/atomic-crm/reporting/domain/performanceDiagnostics.ts — the domain module this page already reads from, but the page keeps its own inline presentation stack",
        ],
        impact=(
            "The dashboard's four reporting windows share one file, so any metric tweak is a "
            "1002-line review; the entropy signal says the file keeps attracting edits, which "
            "compounds the cost."
        ),
        fix=(
            "Move the file-local components into performance/presentation/ grouped by their "
            "window (attention queue, stage matrix, adapter comparison, slowest turns, "
            "supporting stats), share Status/Metric through a small primitives module, and keep "
            "PerformancePage as the composition root. Existing page tests keep their imports "
            "via the same module path or updated spec imports."
        ),
    ),
    dict(
        id="PERF-18",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Batch the per-sibling revision fetch in _reapply_active_sibling_projections (io-in-loop)",
        sev="medium",
        area="performance",
        labels=["io-in-loop", "knowledge"],
        effort="S",
        problem=(
            "category_projections.py's _reapply_active_sibling_projections issues one "
            "await self.db.get(KnowledgeCategoryRevision, ...) per sibling category inside its "
            "for loop (:143) — a classic N+1 on the database boundary, flagged by repowise at "
            "high confidence with loop magnitude growing with data. It runs on the category "
            "revision cutover path, so the query count scales with the project's category count "
            "exactly when an admin is mid-cutover."
        ),
        evidence=[
            "backend/app/services/knowledge/category_projections.py:143 — await self.db.get(KnowledgeCategoryRevision, sibling.active_revision_id) inside for sibling in siblings: (one DB round-trip per iteration)",
            "repowise opportunity perf2_30eeea1fc26b17caa2a2: io_in_loop, boundary db, execution context production, confidence high, effort S / benefit 2.8",
            "backend/app/services/knowledge/category_projections.py:135-141 — the siblings select already returns every row the loop needs keys from",
        ],
        impact=(
            "Cutover latency grows linearly with sibling categories; on a project with many "
            "categories the admin cutover request stacks dozens of sequential round-trips "
            "before the response resolves."
        ),
        fix=(
            "Collect sibling.active_revision_id keys before the loop and fetch once with "
            "select(KnowledgeCategoryRevision).where(<pk>.in_(keys)), then map by id. Validate "
            "result equivalence against the existing projection tests, and keep the None-guard "
            "for revisions deleted between the sibling fetch and the batch read."
        ),
        notes="Adjacent to but distinct from ARCH-23: that card splits category_service.py, this one fixes a query shape in category_projections.py.",
    ),
    # -------------------------------------------------------------- TEST --
    dict(
        id="TEST-23",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Give PersonaForm.tsx a behavioral test file: 609 lines, 58 dependents, zero paired tests",
        sev="medium",
        area="testing",
        labels=["untested-hotspot", "personas"],
        effort="S",
        problem=(
            "PersonaForm.tsx is the worst performer in the repowise production scan (file score "
            "1.65/10) and its untested-hotspot biomarker is explicit: a hotspot with no paired "
            "test file and no coverage data, reaching 58 transitive dependents. The personas "
            "directory carries layout/assignments/list tests, but nothing exercises the create/"
            "edit form's validation or save behavior."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/personas/PersonaForm.tsx — 609 lines, score 1.65/10, untested_hotspot: no paired test file, 58 transitive dependents (repowise get_health production scope)",
            "frontend/src/components/atomic-crm/personas/ — directory tests cover layout regressions, PersonaAssignments, and PersonaList mobile layout; none cover PersonaForm (verified 2026-09-27)",
        ],
        impact=(
            "FE-27-style refactors of the personas surface have no safety net for the form; "
            "validation or save regressions reach QA (or users) undetected, and the file's "
            "deficit will keep ranking it worst-in-repo until behavior is pinned."
        ),
        fix=(
            "Add PersonaForm.test.tsx covering: required-field validation errors, dirty-state "
            "gating of the save action, the happy-path save call with its payload, and the save "
            "failure path. Assert user-visible Vietnamese strings so the test doubles as copy "
            "coverage."
        ),
    ),
]
