# Responsive console polish

Date: 2026-10-02. Base: `239d476eea9e9f74463cd365f4ae2e4445330e47` (`main` and local `origin/main`).

## Scope and acceptance

Run the application locally and improve every supported page and form across phone, tablet and desktop sizes. Preserve the desktop sidebar/top-bar ink design. Deliver the complete uncommitted UI change as a portable Git patch. No deployment, branch, commit, push, PR, production database write or live provider calls.

## Changes

- Dashboard: consistent content width, separate queue surfaces, compact empty states and valid heading/main structure.
- Inbox: calmer list/transcript, old-message dates, accessible reply composer, IME-safe Enter behavior, mobile navigation and a phone-first candidate sheet. Channel filters have no resting boxes; hover, focus and selection remain visible. The unboxed channel glyph sits at the bottom-right of each conversation row, with preview/metadata space reserved so they cannot overlap. Optional details stay collapsed initially. A single identity header shows channel and phone readiness; the three labelled reply modes sit beside the composer. Phone conversation detail supplies its own navigation; Back restores the global bar and directory focus. Desktop chrome keeps its appearance.
- Conversation correctness: accepted mode versions yield to authoritative updates; mode writes cannot overlap or complete into another selected conversation. Pending mode changes preserve the draft and block replies. Explicit successful takeover focuses the composer. Confirmed deletion excludes cached rows through refresh failures.
- Candidate dialog: phone, name, intent and birth year appear first, contact readiness replaces arbitrary field-completion scoring, and edit fields/actions have usable mobile dimensions. Existing version-conflict and pending-save protections remain.
- Projects: coherent directory/create/edit/show surfaces, upload-first creation, clear KB categories, usable source-link forms, keyboard uploads, unique field IDs, context-safe source/category resets, readable activation switches and unclipped category navigation. Nullable legacy knowledge mode renders its actual state instead of calling RAG-only editors and receiving 409 errors. Worker criteria are labelled separately from the twelve knowledge categories.
- Settings: full-width Bot Token/Secret columns, consistent section cards, retryable loading failures and correct App Secret copy. Credential fields discourage saved-login autofill; provider secrets remain concealed by default.
- Accounts/profile: consistent surfaces, cancellation, Vietnamese email validation, wrapping identity text, full-width profile fields, visible switch/select edges and 44px mobile controls. Profile styles are isolated from route-history-dependent inbox CSS.
- Audit: clear outcome/context, readable previews, refresh/count, framed details and rows that contain preview plus metadata at phone widths.
- Performance: framed metrics, retained stale data when background refresh fails, bounded refresh UI, unknown worker state when none is observed, visible mobile diagnostics and hash-safe scrolling/focus to relevant turns.
- Authentication: simpler mobile form, flat desktop form surface, email validation, password visibility, concise inline connection/sign-in errors and no duplicate invalid-form toast. Cancellation is preserved; network failures never automatically retry a write.
- Maintenance: feature-scoped styles reduce the CSS scoping ratchet from 570 to 145. Removed only the newly unreachable generated progress indicator; 29 pre-existing unreachable files remain outside this task. Registry includes the new feature stylesheets and presentation components.

## Verification

- Final full frontend app suite: 120 files, 994 tests passed, including real-browser component tests. Atomic CRM coverage: 83.13% statements, 74.71% branches, 74.79% functions, 85.08% lines; all global and file-specific thresholds pass. `npm run test:unit:app -- --coverage --run --no-file-parallelism --maxWorkers=1`; `/tmp/vfic-ui-polish-full-tests-final.log`.
- App and tooling type checking, registry check (238 files), production build and built-bundle login smoke passed. `/tmp/vfic-ui-polish-{types,node-types,registry,build,smoke}-final.log`.
- Full lint: zero errors; 35 existing warnings in untouched dependency/source code. Changed-source scoped lint and changed-file Prettier passed.
- Initial 32 desktop/mobile E2E journeys: 31 passed; a legacy assertion capped phone adapter tiles at 40px. The new 44px phone target is intentional; the assertion now enforces mobile minimums while preserving desktop caps. Final rerun: all eight checks passed, covering desktop/mobile conversation takeover/release, real audit detail journeys, and four reviewed login visual snapshots. `/tmp/vfic-ui-polish-e2e-confirmed.log`.
- Final screenshot feedback: 19 focused list/filter/CSS tests passed after unboxing filters and moving channel icons. A separate real-modal regression reproduced the undersized candidate portal fields; ten focused tests passed after setting scoped 44px phone fields/actions. The API client connection error now maps to the existing network status for reply sends/retries; 34 focused tests passed, followed by the full 947-test run.
- Final header refinement: 61 presentation/orchestration/transcript/responsive tests, 22 mode-state tests and 11 navigation/deletion Chromium tests pass. The real CSS fixture reproduced a visibility-transition focus race; the final implementation verifies accepted focus, uses the existing transition completion and respects deliberate composer/menu focus. Deletion regressions cover empty/pending snapshots, stale errors and filter remounts. The complete 994-test suite then passes on frozen source.
- Final real-backend E2E: all four desktop/mobile takeover/release and transcript-layout journeys pass in 34.1s, including labelled footer modes, phone header identity focus, direct-detail reload, Back/global bar restoration, selected-row focus and resize/composer measurements. `/tmp/vfic-ui-polish-header-e2e-final.log`. An initial harness startup correctly refused an existing Redis ownership marker; rerun used a separate task-owned loopback Redis instance, then removed it. The populated preview database and its Redis were preserved.
- The first full app run exposed chat-bubble fixtures missing the real workspace scope and one timing-sensitive clipboard test. Corrected the fixture; final full suite passed, and the clipboard test passed unchanged.
- Manual CUA review used populated, synthetic fixtures and genuine RAG/direct-context test projects. Main routes have zero document horizontal overflow at 360×740, 768×1024 and 900×540; one main landmark per route. Additional captures cover 390×844 and 1440×1000, all six settings sections, create/edit dialogs, legacy/RAG/direct-context KB, mobile candidate context, audit and populated performance.
- Independent screenshot review caught and verified fixes for audit row overlap, intrinsic profile field widths, invisible activation/account switches and configuration autofill.
- Final CUA phone proof: identity receives focus after open, Back restores selected-row focus, takeover focuses the reply textarea; 390px header is 79.9px with zero overflow. Desktop 1440px header is 65px, the dark bar is visible and the sidebar/top-bar ink line is intact. Temporary viewport override reset and the populated preview retained.
- Desktop sidebar, top-bar, token and workspace-rail designs are preserved. The shell source change imports a stylesheet whose rules apply only at widths below 768px. Agent routing check passed (32 paths / 4 make targets). Whitespace checks passed.

## Local preview and evidence

The local preview uses the test-only backend harness and a task-owned PostgreSQL database ending in `_e2e`, on loopback port 5443, plus Redis on 6382. The harness blocks external connections and blanks provider credentials. The standard development seed supplies synthetic conversations, candidates, telemetry and documents. Preview URL: `http://127.0.0.1:4173`; final session credentials: `admin@vfic.dev` / `admin123` (synthetic local account only).

Screenshots and geometry evidence are exported alongside the patch under `plans/exports/2026-10-02-ui-polish-screens/`. Test logs are copied to `plans/exports/2026-10-02-ui-polish-checks/`.

## Practical limits

This verifies the local application, component contracts and Chromium desktop/mobile journeys. No production deployment or live Zalo/Messenger/LLM/OTP delivery was exercised. The four macOS login visual snapshots were intentionally refreshed and reviewed; Linux-specific baselines must be refreshed in a Linux browser environment for the intentional authentication redesign. Existing legacy projects without an owned KB retain their documents and export access; editor access still requires the supported backend bootstrap/ownership workflow.
