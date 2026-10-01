# Complete answers, project knowledge, and production UX audit

Date: 2026-10-01. Combined patch base on `main`:
`35d970689cbb092e4f9100f1e60305c9bd7505ed`.

The deliverable is an uncommitted portable patch named
`2026-10-01-complete-answers-production-audit.patch`, including source,
regressions, workflow documentation, and audit/completion records. No branch,
commit, push, pull request, merge, or deployment was requested or performed.
The final exact backend counts, command results, and export verification are
recorded in
[the completion record](261001-2110-complete-answers-production-audit-completion.md).
The export manifest is
`plans/exports/2026-10-01-complete-answers-production-audit.manifest.json`.

The audit found that the earlier training/recruitment audit changes were not
present in this main baseline. Those fixes were restored while preserving the
newer UI, then checked together with the current changes. The older
[main audit report](261001-1545-main-audit.md) describes the original work on
`21cd171313bf0366e812a1e4ce379b47f633981c`; its historical test totals are not
the verification totals for this combined patch.

## Acceptance and scope

The project is the unit of recruitment. Candidate discovery must use the
complete active-project catalog within the channel's authorized scope; details
must come from the selected project's current knowledge. One uploaded brief
must prepare supported category evidence and features without exposing a
mixed publication. Intake priority remains mobile number mandatory, full name
highly recommended, nguyện vọng useful when supplied, and birth year optional.
Missing optional fields must not block project advice or recruiter follow-up.

The concrete answer defect had several causes. A 450-character presentation
cutoff discarded generated content, exploration instructions encouraged a
small shortlist even when the candidate requested every project, and model
output-cap recovery could consume the last normal loop round without actually
continuing. Progressive sending and transport/receipt handling could then make
an incomplete logical answer appear complete. The repair spans those
boundaries instead of increasing a token limit alone.

UI scope covers every reachable runtime page and its major loading, empty,
error, editing, saving, and destructive-action states. The established slate
console, Be Vietnam Pro typography, Vietnamese copy, 40-pixel button ceiling,
and 12-pixel labels are preserved. Installed Untitled UI primitives and existing
adapters were used; official input, modal, table, and application UI catalogs
were consulted because the component MCPs were unavailable. Dependency-owned
generated components were not edited. No dependency upgrades or schema
migrations were added.

## Answer completeness and delivery

| Root cause                                                                                                                                                                                           | Resulting behavior                                                                                                                                                                                                                                                                                                                                                           | Regression evidence                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Presentation compaction removed content after a short Zalo budget and appended a request to ask for more.                                                                                            | The reply boundary preserves the complete sanitized model answer; there is no 450-character factual cutoff.                                                                                                                                                                                                                                                                  | `test_graph_runner_turn.py` covers long catalog output and complete answer preservation. Obsolete compaction expectations were removed.                                                                                                                             |
| A full-catalog request could still be treated as a small recommendation set, and a focused direct page could bypass catalog authority.                                                               | Vacancy/catalog routing requires `list_active_projects` for the turn. Discovery, route hints, and the tool presentation contract require every returned project exactly once for an explicit all-project request. Focused direct context cannot override a required authority tool.                                                                                          | Graph runner/factory regressions cover catalog routing, focused direct context, recent vacancy follow-up, and complete five-project output.                                                                                                                         |
| Continuation depended on remaining normal tool-loop rounds; after repeated provider caps, trimming a dangling tail still presented an incomplete list.                                               | A separate bounded recovery allowance permits up to two tool-free continuations and one concise complete rewrite over the same evidence, including after the final normal round. An empty or still-capped rewrite is suppressed and recorded as a completion failure. Native and markup tool calls cannot re-enter dispatch during recovery.                                 | `test_answer_completion_guard.py` covers final-round recovery, bounded exhaustion, seam deduplication, complete rewrite, capped rewrite suppression, and unexpected tool calls. A normal `stop` answer remains unchanged and costs one generation call.             |
| A catalog's first streamed bubble could reach the candidate before completion/rewrite, leaving the first two rows committed. A rejected raw stream tail could also survive a corrected final answer. | Catalog turns wait for the completed answer. Other progressive turns retain a verified early prefix; the remainder follows the finalized grounded answer rather than discarded stream text.                                                                                                                                                                                  | Graph runner regressions cover deferred catalog streaming, finalized remainder, replacement, empty final answer, and non-catalog progressive behavior.                                                                                                              |
| Long replies lacked a shared provider-neutral bounded transport contract. A later failure could replay an already accepted prefix or lose uncertainty when the accepted send had no returned ID.     | Shared plain-text splitting preserves words/order and sends bounded parts, with current account generation and policy checked before each provider call. Partial acceptance is tracked independently of returned IDs. A failure after acceptance becomes an unknown send outcome and retains the accepted ID when available; the whole answer is not automatically replayed. | `test_channel_dispatch.py` covers Zalo and real Messenger adapter chunking, policy expiry, account replacement, future-generation rejection, later exceptions/rejections, and first-part definite failure. Zalo service tests cover partial acceptance without IDs. |
| A receipt for any message in a conversation promoted unrelated id-less `SEND_UNKNOWN` rows; a prefix receipt could confirm a logical answer with an unsent tail.                                     | Only exact stored provider-message IDs advance delivery. Id-less uncertain sends remain uncertain. A persisted partial-delivery marker prevents accepted-prefix receipts from claiming complete delivery.                                                                                                                                                                    | Real PostgreSQL `test_delivery_receipt_send_unknown.py` covers unrelated/unknown IDs, matched-only advancement, partial tails, delivered/read ordering, and non-revival of failed/suppressed rows.                                                                  |

The shared splitter uses a 1,600-character default budget and prefers
paragraphs, then sentences, then words. Oversized individual tokens are split
only when necessary. Whitespace can normalize across bubbles; factual content
is not intentionally shortened or reordered. Existing channel-specific sends
continue to use their configured transport budget.

This approach trades an early catalog bubble for complete-answer handling and
adds bounded model work only when the provider reports an output cap. It does
not fabricate a deterministic substitute project answer. A provider returning
`finish_reason=stop` while semantically omitting projects is still addressed by
the exhaustive-list prompt/tool contract, not a deterministic semantic
completeness validator. That limitation is explicit.

## Restored training, KB, caching, and intake fixes

| Root cause                                                                                                                                                                     | Resulting behavior                                                                                                                                                                                                                                                                                                                | Regression evidence                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| One-file training published categories/features separately and validated new Job IDs against old siblings.                                                                     | Prepare extraction, revisions, and embeddings privately; validate the complete proposed graph plus retained active siblings; publish category pointers, evidence, Jobs/routes, features, highlights, and source completion in one transaction. Failed preparation/publication preserves the prior snapshot.                       | Real PostgreSQL `test_project_training.py` covers coherent Job ID replacement, embedding failure, and transactional rollback.                                                                                                                                       |
| A duplicate delivery at the final allowed attempt revoked a live worker claim.                                                                                                 | Preserve an unexpired processing owner before enforcing the attempt cap.                                                                                                                                                                                                                                                          | Category/training regressions cover duplicate delivery with a live final-attempt token.                                                                                                                                                                             |
| Legacy shadow training exposed new features before KB cutover; rollback omitted adopted feature rows. Passive feature reads and obsolete sources also confused freshness.      | Defer source-owned features/highlights until explicit cutover. Adopt only current matching prepared intent, retain newer independent edits, restore exact feature snapshots on rollback, ignore untouched generated gaps, and close obsolete completed deferred intents. The receipt/UI distinguish preparation from publication. | PostgreSQL training tests cover old salary/highlight preservation, cutover, stale-source exclusion, independent edits, generated rows, rollback, and same-file reupload. Frontend ingest tests cover `requires_cutover` and no browser replay of shadow highlights. |
| Revision/source deduplication could reuse a superseded intent or let a stale batch overwrite manual changes.                                                                   | Serialize intent against the project, reuse valid current checkpoints, create fresh intent after manual supersession, and reject individual retries of source-owned categories with guidance to retry the batch.                                                                                                                  | Training/category tests cover A → pending B → A, manual supersession, interrupted ownership, explicit reprocess, and exact-file reuse.                                                                                                                              |
| Retrieval self-test accepted another record's matching embedding; OOXML extraction had expansion/reference amplification risks.                                                | Compare each sampled question/title with its own aligned embedding and reject non-finite similarity. Bound archive members, expanded content, XML reads, XLSX text/columns, encrypted archives, and repeated worksheet references.                                                                                                | `test_retrieval_selftest.py` rejects swapped vectors/unrelated matching siblings; `test_knowledge_upload_formats.py` covers adversarial and normal Office extraction.                                                                                               |
| Direct-context resolution bypassed Page assignment scope and trusted cached inactive or superseded identities. Category catalog rows did not require the active Jobs revision. | Apply Messenger Page assignments to discovery and focused context; refresh named/focused active state, aliases, current KB and mode from the database. Require category-derived Jobs to match the active authoritative Jobs pointer.                                                                                              | Real PostgreSQL `test_recruitment_project_scope.py` warms the global catalog before assignment, deactivation, and KB/mode replacement checks. Catalog regressions reject stale revisions.                                                                           |
| Shared prose caching omitted private intake/provider context and history; cache generations/expiry allowed stale cross-turn results.                                           | Hash intake/provider context; bypass shared prose reuse when prior history exists. Use random safe generations with concurrent initializer convergence, independent semantic expiry and access LRU, and capture generation before retrieval so an old computation cannot write into a newer scope.                                | Answer-cache, core-cache, and semantic-cache tests cover candidate/provider isolation, history, counter loss/concurrency, expiry/LRU, and invalidation during retrieval.                                                                                            |
| Candidate denials/questions looked affirmative; a rejected CRM phone counted valid again and delayed extraction could restore it.                                              | Use ownership-aware phone/name evidence. Clear only an explicitly rejected matching current mobile, retain typed audit evidence, and order corrections/confirmations by durable inbound time. Fence both upsert paths against older extraction.                                                                                   | Vietnamese intake evidence tests and real PostgreSQL `test_candidate_phone_evidence.py` cover third-party numbers, denial, reconfirmation/correction, repeated/late events, Zalo/Messenger, and deferred merge.                                                     |

One brief fills categories only where the source supports the facts. Missing
categories retain existing published content or remain reviewable; the system
does not invent salary, eligibility, benefits, contacts, or optional candidate
fields. Publication locks do not span provider I/O. Cache repair follows commit.
The aligned-embedding gate is retrieval sanity evidence, not proof of factual
entailment or a guarantee of rank against the entire knowledge base.

## Account security and concurrent administration

| Root cause                                                                                                                                                                   | Resulting behavior                                                                                                                                                                                                                                     | Regression evidence                                                                                                                                                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| An ORM identity-map hit could supply an old token generation, password hash, disabled flag, or account role after another request changed it.                                | Refresh current security state under the appropriate row/lifecycle lock before logout, password change/reset, and administrative lifecycle updates. Refresh-token checks reload authority. Each overlapping revocation advances the latest generation. | `test_auth_token_revocation.py` and real PostgreSQL `test_identity_security_generation.py` cover preloaded users, overlapping logout/password/admin reset, current-hash recheck, revoked refresh, and disabled accounts. |
| An OTP sent to an old mailbox could reset an account after its email changed.                                                                                                | Consume/reject the challenge unless the current locked user's normalized mailbox still matches the issued challenge.                                                                                                                                   | Real PostgreSQL identity security regression covers an OTP issued before account email replacement.                                                                                                                      |
| Last-admin guards read account state before serialization; nullable patch fields and rollback attribute access could cause wrong state or an unexpected async ORM exception. | Lock first and reload the user, ignore explicit null for non-nullable account fields, and retain the attempted email before rollback so duplicate-email conflicts remain expected errors.                                                              | Real PostgreSQL `test_user_lifecycle_guards.py` covers stale promoted users, last-admin protection, nullable patches, duplicate-email rollback, and password reset generation.                                           |

The changes preserve the existing transport/application/domain boundaries,
structured logging, audit events, and async crypto offload. No plaintext
credentials or candidate message content were added to logs.

## Reachable page and form inventory

Routes below are runtime contributions rather than unused source files. Route
paths are shown without the application's hash prefix. Existing correct
controls were retained instead of being rewritten solely to claim coverage.

| Reachable surface                                         | Audited states and forms                                                                                                                                                                   | Outcome                                                                                                                                                                                                                                                                                                                                               |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/`: Dashboard / RecruitingCommandCenter                  | Recruitment queues, grouping/date/range, candidate rows, full CandidateDataDialog profile; initial loading, no candidates, partial error/retained cache, retry, save/cancel.               | Existing feature hierarchy and dialog pending/validation contracts retained; shared shell/table/scroll improvements apply.                                                                                                                                                                                                                            |
| `/conversations`, `/:id/show`                             | Channel/search/filter/pagination/deep link, transcript/composer/mode, candidate profile and decision trace; loading/error/empty, takeover/release, editing/saving, mobile sheet.           | Pending candidate save owns its lead ID, blocks dismiss/close, retains failed draft with inline error. Theme scope and Vietnamese trace labels corrected. Restored ChatThread observer repair coalesces layout work without native ResizeObserver errors or stealing reader position.                                                                 |
| `/projects`                                               | Search/status/readiness, active toggle, list/detail expansion, paging and empty/error states.                                                                                              | Existing responsive cards/actions retained; unread/unfinished knowledge still blocks unsafe activation.                                                                                                                                                                                                                                               |
| `/projects/create`, `/:id/edit`, `/:id/show`              | One-file preview/confirm/create/activate, name/status, categories/template/source/revision/retry/poll, cutover/rollback, FAQ and bus timetable.                                            | Restored ingest/category guards preserve authoritative publication and request ownership. Category fallback labels are Vietnamese while catalog data loads. Bus fetch failure offers retry instead of false emptiness, with project-scoped pagination and snapshot.                                                                                   |
| Project direct-context page and discovery card            | Filename/content/file read/replace, read-only state, background Sheet sync, unsaved draft, source errors; discovery summary/location/roles/highlights/aliases/eligibility.                 | Remote content never silently overwrites unsaved text; repeat sync retains warning until save/discard/matching draft. Old file/save responses cannot alter another project. Unreadable/oversized files preserve the draft. Read failure fails closed with retry. Visible discovery labels and save locks added; hidden eligibility remains preserved. |
| Project Google Sheet link/list/rows                       | URL/gid/category/schedule/import, source status/auto-sync/failure, run-now cooldown/delete, worker follow-up and hidden-tab polling.                                                       | Failed read no longer becomes “no sources.” Retry retains known rows. Run/delete/create are scope-owned, guard duplicates, and lock pending actions; late results cannot affect another project. Existing bounded polling/visibility contracts retained.                                                                                              |
| `/bot_runs`, `/:id/show`                                  | Outcome/conversation filters, read-only paginated records, badges/facts, trace expansion; loading/error/retry/empty.                                                                       | Existing responsive detail/table contracts retained; trace action/title/content localized as “Suy luận chatbot.”                                                                                                                                                                                                                                      |
| `/users`, `/users/create`, `/:id/edit`                    | Directory/avatar/role/status/date/pager, create/edit name/email/role/active, enable/disable/reset/delete.                                                                                  | Count uses total rather than visible page size; permission loading is announced. Create has inline password length/confirmation checks. Pending fields/cancel locked; overlapping row mutations prevented. Reset keeps error/draft and focuses invalid input; reset/delete cannot dismiss during a write.                                             |
| `/profile`                                                | Profile loading/read failure/view/edit/validation/save/cancel/logout.                                                                                                                      | Announced loading and retry replace blank/unsafe forms; validation is associated and pending edits/cancel are locked. Existing card/navigation retained.                                                                                                                                                                                              |
| `/login`, `/forgot-password`, StartPage and LoginSkeleton | Email/password/reveal, recovery email/OTP/new-password/confirmation/resend/back/success; required validation, pending, lazy-route load.                                                    | Required errors are visible, associated and focused; themed actions and pending locks added. Existing recovery/resend contracts and stable suspense shell retained.                                                                                                                                                                                   |
| `/hieu-suat`                                              | Window selector/refresh, initial load/error/retry/no activity, six metrics/trend, attention queue, slow-turn details/mobile cards, stage matrix/mobile diagnostics, adapter/support stats. | Existing responsive cards/charts and diagnostic state contracts audited and retained.                                                                                                                                                                                                                                                                 |
| `/settings` and legacy redirects                          | Six section views below, desktop navigation/mobile drawer, permission loading; `/settings/profile` → profile and `/zalo_integrations/*` → settings.                                        | No editable settings appear before administrator permissions resolve. Existing navigation and redirect contracts preserved.                                                                                                                                                                                                                           |

There is no separate reachable leads resource: recruitment lead forms live in
dashboard and conversation candidate profiles. The settings resource has six
actual sections, rather than the stale seven-section source description.

| Settings section               | Forms and states                                                                                                                                          | Fix or retained contract                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Zalo Chatbot and recruiting OA | Credentials, masked/revealed/copied secrets, status, save-and-test, missing configuration, pending/error.                                                 | Saving one scope no longer clears the other scope's unsaved credentials or newer values. Probe errors are handled and pending operations guarded/locked.                                                                                                                                                                                                                   |
| AI Providers                   | Three provider cards, enable/default/failover order, credential/model fields, probe receipt, save/discard.                                                | Group reset preserves Jev's draft; functional enabled-state updates retain other-group state. Duplicate save/probe guards, caught probe errors, and pending/loading/error controls added.                                                                                                                                                                                  |
| Jev                            | Standalone enable/credentials/model/probe/save.                                                                                                           | Uses the same retained-other-group reset and pending/loading locks.                                                                                                                                                                                                                                                                                                        |
| TingTing                       | OTP/reset integration API key/hotline/App ID/OA secrets/tokens/link status/check/save-and-test.                                                           | Unreadable settings fail closed with explicit retry; read/write/check fields and actions are locked appropriately.                                                                                                                                                                                                                                                         |
| Internal users                 | Embedded directory/create/edit/account actions.                                                                                                           | Shares the corrected users contracts above.                                                                                                                                                                                                                                                                                                                                |
| Messenger                      | Meta credentials, connection status/test, OAuth callback/manual recovery/Page choice, assigned active projects, connected/archived Page cards/disconnect. | Assignment read failure cannot become an editable empty replacement set. Retry precedes editing and assignment controls lock during save. Status failure cannot claim “Chưa kết nối”; known status is retained with retry. Credentials lock pending/loading/error, retry is available, and duplicate submit is guarded. Existing secret masking and OAuth recovery remain. |

Shared fixes align the 768–1023-pixel document scroll owner with the shell's
1024-pixel rail breakpoint, keeping long tablet forms reachable. Modal/sheet
height is bounded to the dynamic viewport with internal scrolling and touch
close controls; safe-area topbar padding is retained. List errors are announced
with retry instead of falsely displaying an empty directory, and pager/layout
controls remain reachable at narrow widths. Shared fields preserve validation,
focus/ref, required/disabled/read-only behavior and associated descriptions;
password reveal controls use Vietnamese labels without implicit form submit.
Pending confirmations cannot dismiss. Skip navigation focuses main content
without changing the hash route, and command navigation stays inside the
hash-routed workspace.

The custom bot-run timeline previously bypassed the shared table error state and
claimed there were no runs when its initial request failed. It now announces
that failure with retry, retains known rows after background errors, reports a
failed retry, and exposes real loading/retry activity. Six additional browser
unit regressions cover these states (`BotRunPages.test.tsx`).

The screenshot review also found that the global flat-surface rule erased
InputBase shadow-based outlines, leaving authentication fields without clear
idle/focus/error bounds. The non-generated theme adapter restores physical
field outlines and suitable contrast while keeping surfaces flat. Real browser
regressions cover login and recovery idle/focus/error states without changing
layout. Visual baselines are intentionally refreshed for current branding and
the supported light theme under both light/dark system preferences, with a
1% image-difference ceiling instead of 10%. macOS and Linux results are in the
completion record; no unsupported forced hybrid dark theme is asserted.

## Verification and evidence boundaries

| Check                               | Current evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full frontend browser-unit coverage | 853 tests in 117 files pass. Statements 81.69%, branches 72.40%, functions 73.69%, lines 83.76%.                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Responsive functional E2E           | 26 tests pass. Ten main pages are exercised at 360, 390, 768, 900, 1024, and 1440 pixels, with route-specific assertions. Additional journeys cover all six settings views on phone/desktop, real short-tablet account creation/validation, project detail, keyboard navigation, one-file creation, and conversation mode/layout changes.                                                                                                                                                                                              |
| Feature regression checkpoint       | 192 tests in 19 affected feature files pass; the focused settings/source/trace checkpoint is 70 tests in six files. These are subsets, not additional tests to add to the full-suite total.                                                                                                                                                                                                                                                                                                                                            |
| Frontend static and bundle checks   | App/node typecheck, build, registry validation, and built-bundle smoke pass. Full lint has zero errors and 35 existing warnings; warnings are retained.                                                                                                                                                                                                                                                                                                                                                                                |
| Backend regression coverage         | 3,065 non-integration tests pass (37 skipped), coverage 77.41% above the 75% gate; 243 PostgreSQL integration tests pass, including the complete migration reverse/reapply walk. Completion, catalog/progressive output, channel chunk/fence/receipt, training publication, retrieval/cache/intake, and identity/account suites include the regression cases listed above. Final aggregate counts, coverage, integration/migration evidence, and command outcomes are in the completion record. Historical counts are not substituted. |
| Supported-theme visual comparisons  | Four macOS and four Linux desktop/mobile comparisons pass after intentional regeneration of all eight current-brand baselines. Both system preferences retain the supported light theme; 1% image-difference ceiling.                                                                                                                                                                                                                                                                                                                  |
| Source and export checks            | Changed-file formatting and diff whitespace checks pass. Exact-base patch apply/reverse/content/mode verification and artifact hashes/file inventory belong to the final completion record and manifest. This report does not assert an export result before that verification finishes.                                                                                                                                                                                                                                               |

Feature checkpoint logs are retained locally as
`/tmp/vfic-screen-combined-final.log`,
`/tmp/vfic-screen-settings-final.log`,
`/tmp/vfic-screen-typecheck-final.log`, and
`/tmp/vfic-screen-eslint-final.log`. Original regression failures were used to
prove the defects before fixes; they were not removed by weakening assertions.
The combined hook checkpoint contains React test `act` warnings; those are
test-harness observations, not evidence of a deployed application error.
Final broader logs and browser artifacts are recorded by the completion owner.

The route audit corrected a pre-existing `/bot-runs` test path to actual
`/bot_runs` and replaced generic-main-heading acceptance with real route
assertions, so a missing route cannot pass as page coverage. Loaded-data checks
are used for visual review; a framework loading skeleton is not treated as a
finished page.

## Remaining limits and patch application

- Local controlled-provider tests and migrated disposable PostgreSQL/Redis
  checks establish regression behavior. They do not prove live-provider answer
  quality, real outbound delivery, production data correctness, or deployment.
- A normal provider stop with a semantically incomplete list remains governed
  by the complete-catalog prompt/tool contract. Output-cap continuation and
  rewrite suppression provide a separate measurable completion guard.
- Catalog answers wait for full generation; cap recovery can add bounded model
  latency. The offline retrieval golden latency SLO is deliberately disabled,
  so this audit does not claim production latency compliance.
- Unknown/partial send outcomes stay uncertain for review instead of being
  automatically replayed or confirmed from unrelated receipts. A candidate may
  have received only the accepted prefix when a later part failed.
- Missing or ambiguous extracted source facts require administrator review.
  The upload pipeline cannot infer facts absent from the source or guarantee
  perfect semantic extraction. Cache repair remains bounded/best effort after
  a successful database commit.
- Existing warnings and dependency-audit observations remain visible. No
  forced dependency upgrade, gate exemption, or clean-checkout release bypass
  was introduced for uncommitted patch delivery.

On the other machine, start from the exact base above and check the exported
patch before applying it:

```sh
git rev-parse HEAD
git apply --check 2026-10-01-complete-answers-production-audit.patch
git apply 2026-10-01-complete-answers-production-audit.patch
```

The completion record and manifest provide the final SHA-256, included-file
inventory, exact-baseline verification, and final test counts. Applying this
patch changes local source only; it does not deploy or run database commands.
