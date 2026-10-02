# Journals

Durable post-mortems and work records: what happened, what was tried, what
failed, and what the next session needs to know. `docs/decisions/` owns ADRs;
`plans/reports/` owns per-change completion records. This directory holds the
narrative record between the two.

Add one file per incident or multi-session effort, named
`<YYMMDD[-HHMM]>-<slug>.md` (or `YYYY-MM-DD-<slug>.md`), and append a row
below. Journals are never pruned; they are the institutional memory for
regression analysis and onboarding.

| Date | Topic | File |
|---|---|---|
| 2026-07-22 | Single-page Google Sheet sync deployment | [2026-07-22-single-page-google-sheet-sync-deploy.md](2026-07-22-single-page-google-sheet-sync-deploy.md) |
| 2026-07-11 | Graphite, Cloud, and Emerald UI Refactor | [260711-graphite-cloud-ui-refactor.md](260711-graphite-cloud-ui-refactor.md) |
| 2026-07-12 | Dashboard /attention 500 — SET LOCAL on a shared request session | [260712-dashboard-attention-500-set-local.md](260712-dashboard-attention-500-set-local.md) |
| 2026-07-12 | Delivery retry containment and worker outcome regression | [260712-delivery-retry-worker-regression.md](260712-delivery-retry-worker-regression.md) |
| 2026-07-12 | Messaging hardening — one real bug, three instrumentation adds, five rejected | [260712-messaging-hardening-send-unknown.md](260712-messaging-hardening-send-unknown.md) |
| 2026-07-12 | Performance endpoint — alembic double-head fork that the test suite cannot see | [260712-performance-endpoint-alembic-double-head.md](260712-performance-endpoint-alembic-double-head.md) |
| 2026-07-12 | Recruiter attention dashboard implementation | [260712-recruiter-attention-dashboard-implementation.md](260712-recruiter-attention-dashboard-implementation.md) |
| 2026-07-12 | Recruiter attention dashboard direction | [260712-recruiter-attention-dashboard.md](260712-recruiter-attention-dashboard.md) |
| 2026-07-12 | Zalo candidate avatars — full-stack feature from zero | [260712-zalo-candidate-avatars.md](260712-zalo-candidate-avatars.md) |
| 2026-07-12 | Zalo OA webhook user resolution — three bugs, one flawed assumption | [260712-zalo-oa-webhook-user-resolution.md](260712-zalo-oa-webhook-user-resolution.md) |
| 2026-07-14 | Journal: 2026-07-14 — ACTIVE-job grounding | [260714-2233-active-job-grounding.md](260714-2233-active-job-grounding.md) |
| 2026-07-15 | Journal: 2026-07-15 — Universal platform phase one | [260715-0958-universal-platform-phase-one.md](260715-0958-universal-platform-phase-one.md) |
| 2026-07-15 | Journal: 2026-07-15 — Repository agent development kit | [260715-agent-development-kit.md](260715-agent-development-kit.md) |
| 2026-07-15 | Journal: 2026-07-15 — Atomic candidate notes | [260715-atomic-candidate-notes.md](260715-atomic-candidate-notes.md) |
| 2026-07-15 | Journal: 2026-07-15 — Conversation viewport and scroll affordance | [260715-conversation-scroll-affordance.md](260715-conversation-scroll-affordance.md) |
| 2026-07-15 | Journal: 2026-07-15 — Universal industry platform plan | [260715-universal-industry-platform-plan.md](260715-universal-industry-platform-plan.md) |
| 2026-07-15 | Journal: 2026-07-15 — Universal installation lifecycle | [260715-universal-installation-lifecycle.md](260715-universal-installation-lifecycle.md) |
| 2026-07-15 | Journal: 2026-07-15 — Restore legacy webhook processing while installation is inactive | [260715-webhook-installation-recovery.md](260715-webhook-installation-recovery.md) |
| 2026-07-16 | Journal: 2026-07-16 — Inbox attention badge | [260716-inbox-attention-badge.md](260716-inbox-attention-badge.md) |
| 2026-07-17 | Journal: 2026-07-17 — Channel adapter observability | [260717-1316-channel-adapter-observability.md](260717-1316-channel-adapter-observability.md) |
| 2026-07-17 | Journal: 2026-07-17 — Vacancy Answering Bug Fix | [260717-2309-vacancy-answering-bug-fix.md](260717-2309-vacancy-answering-bug-fix.md) |
| 2026-07-18 | Journal: Messenger integration repair | [260718-1733-messenger-integration-repair.md](260718-1733-messenger-integration-repair.md) |
| 2026-07-18 | Journal: Facebook OAuth dialog host fix | [260718-1810-facebook-oauth-dialog-host-fix.md](260718-1810-facebook-oauth-dialog-host-fix.md) |
| 2026-07-18 | Zalo empty-generation recovery | [260718-1845-zalo-empty-generation-recovery.md](260718-1845-zalo-empty-generation-recovery.md) |
| 2026-07-18 | Data ingestion cutover recovery | [260718-1947-data-ingestion-cutover-recovery.md](260718-1947-data-ingestion-cutover-recovery.md) |
| 2026-07-18 | split_for_digest boundary-aware chunking fix | [260718-2100-split-for-digest-boundary-fix.md](260718-2100-split-for-digest-boundary-fix.md) |
| 2026-07-18 | Journal: Project-Owned Exclusive Single-page/RAG | [260718-project-knowledge-modes.md](260718-project-knowledge-modes.md) |
| 2026-07-18 | Journal: Terse Vacancy Follow-up Routing | [260718-terse-vacancy-followup-routing.md](260718-terse-vacancy-followup-routing.md) |
| 2026-07-22 | Blue-green production deploy recovery | [260722-1547-blue-green-production-deploy-recovery.md](260722-1547-blue-green-production-deploy-recovery.md) |
| 2026-07-22 | OA profile backfill hardening | [260722-1705-oa-profile-backfill-hardening.md](260722-1705-oa-profile-backfill-hardening.md) |
| 2026-07-22 | Journal: 2026-07-22 20:13 - Single-page vacancy catalog drift | [260722-2013-single-page-vacancy-catalog.md](260722-2013-single-page-vacancy-catalog.md) |
| 2026-07-22 | Reply policy boundary leak | [260722-2059-reply-policy-boundary.md](260722-2059-reply-policy-boundary.md) |
| 2026-07-22 | Phase 1 DDD baseline and production cutover | [260722-2156-phase-1-ddd-baseline-production-cutover.md](260722-2156-phase-1-ddd-baseline-production-cutover.md) |
| 2026-07-22 | Working-hours contradiction recovery | [260722-2315-working-hours-contradiction-recovery.md](260722-2315-working-hours-contradiction-recovery.md) |
| 2026-07-22 | One-page Project activation | [260722-one-page-project-activation.md](260722-one-page-project-activation.md) |
| 2026-07-23 | KB sync cron pinning | [260723-1103-kb-sync-cron-pinning.md](260723-1103-kb-sync-cron-pinning.md) |
| 2026-07-23 | Candidate display-name overwrite fix | [260723-2046-candidate-display-name-overwrite-fix.md](260723-2046-candidate-display-name-overwrite-fix.md) |
| 2026-07-26 | Release and Frontend Hardening Learned the Hard Way | [260726-2119-release-frontend-hardening-retrospective.md](260726-2119-release-frontend-hardening-retrospective.md) |
| 2026-09-06 | Journal: Facebook Messenger webhook-subscription readiness check | [260906-0020-facebook-subscription-readiness-check.md](260906-0020-facebook-subscription-readiness-check.md) |
| 2026-10-02 | KB evidence grounding — compare words, not formatting | [261002-evidence-grounding-word-tokens.md](261002-evidence-grounding-word-tokens.md) |
