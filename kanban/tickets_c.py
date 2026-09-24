"""Frontend + testing tickets."""

TICKETS = [
    dict(
        id="FE-01",
        title="ZaloIntegrationPage is a 2072-LOC module whose one component owns four product domains",
        sev="high",
        area="frontend",
        labels=["tech-debt"],
        effort="L",
        problem=(
            "`ZaloIntegrationPage.tsx` is 2072 LOC, of which a single component is ~1100 LOC with 19 "
            "`useState` owning four product domains: the Zalo channel form, the LLM provider "
            "descriptors, the JEV panel, and three pages embedded from other products. Load, save, "
            "dirty-check and test logic is inlined rather than extracted, and three separate "
            "save/dirty mechanisms coexist in the same file."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:973-2072` — one component of ~1100 LOC; the module totals 2072 LOC.",
            "`frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:978-1007` — 19 `useState` in that one function (settings, providerSettings, settingsStatusState, form, providerForm, providerEnabled, providerTesting, providerSaving, providerLastTests, llmDefaultProvider, llmFailoverOrder, activeItemId, testingBot, testingOa).",
            "`frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:1483-1505` — `renderSettingsBody()` branches over 6 sections and mounts other products' pages: `<PersonaList embedded />` `:1487`, `<UserList embedded />` `:1495`, `<FacebookMessengerIntegrationPage />` `:1501`.",
            "`frontend/src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx:1080-1082` — the comment explicitly acknowledges that `llmContext` identity changes on every render.",
            "Inlined load/save/test logic instead of hooks: `load` `:1014-1063`, `providerPayload` `:1089-1121`, `hasProviderPanelEdits` `:1123`, `saveProviderPanels` `:1127-1169`, `discardProviderPanels` `:1171-1186`, `testProviderPanel` `:1188-1236`, `handleProviderEnabledChange` `:1259-1280`.",
        ],
        impact=(
            "Any change to one integration risks the other three, because the LLM descriptor "
            "machinery and the Zalo form share state and the same render function. The whole Settings "
            "resource is one lazy chunk that must be parsed as a single unit, and the main component "
            "re-renders on every keystroke in any of ~40 fields."
        ),
        fix=(
            "Extract along the seams the audit names: `integrations/domain/providerDescriptors.ts` "
            "(move `:82-465` types and `PROVIDER_PANELS_BY_ID`), `application/useSettingsBundle.ts` "
            "(owns `load`), `application/useZaloForm.ts`, `application/useProviderPanels.ts` (owns 7 "
            "`useState` + 5 handlers — the single biggest win), `presentation/SettingsChrome.tsx`, "
            "`ZaloChannelSection.tsx`, `LlmProvidersSection.tsx` and `JevSection.tsx`, leaving a "
            "~120-LOC shell. Move the three embedded foreign pages (`settings-agents`, "
            "`settings-users`, `settings-facebook-messenger`) to the routes that own those products."
        ),
    ),
    dict(
        id="FE-02",
        title="ProjectKnowledgePanel mixes three data-access idioms across 1095 LOC and 21 useState",
        sev="high",
        area="frontend",
        labels=["tech-debt"],
        effort="L",
        problem=(
            "`ProjectKnowledgePanel.tsx` is 1095 LOC whose `RagCategoriesPanel` alone is 623 LOC with "
            "12 `useState`, and it talks to the same backend through three different idioms: a plain "
            "service facade driven by local state, react-admin's `useDataProvider`, and `useRefresh()` "
            "used to force react-admin refetches after facade writes. The two panels also duplicate "
            "hand-rolled `active`/`requestId` generation guards, and one effect disables "
            "`exhaustive-deps` because its loader is an unstable closure."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:358-980` — `RagCategoriesPanel` is 623 LOC with 12 `useState` `:360-373`; `SinglePagePanel` `:66-356` adds 9 more at `:69-77`.",
            "`frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:80-133` and `:414-503` — plain service-facade calls (`project-knowledge-service.ts`) driven by local `useState`.",
            "`frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:982-985` — `DiscoveryCardEditor` calls `useDataProvider<CrmDataProvider>()`, a second write path to the same resource; `useRefresh()` from ra-core at `:67`/`:984` forces refetches after the facade path writes.",
            "`frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:78`, `:375`, `:414-457` — two independent generation guards (`loadRequestRef`, `pollRef`) and two separate effects doing the same load.",
            "`frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:416-417` — `eslint-disable-next-line react-hooks/exhaustive-deps` because `loadCatalog` is an unstable closure.",
        ],
        impact=(
            "Two panels write the same resource through different paths, so cache coherence depends on "
            "manual `refresh()` calls. Every save and upload carries its own loading/error/notification "
            "triad, and the 623-LOC panel cannot be tested in isolation."
        ),
        fix=(
            "Introduce `useProjectKnowledgeCatalog(projectId)` (query + mutations, owns "
            "`pollUntilActive`), `useCategoryDraft(projectId, key)` and `useSinglePageDraft(projectId)`, "
            "with pure `CategoryEditor`, `SinglePageEditor`, `FaqAutoSyncSection` and "
            "`DiscoveryCardEditor` components. Route all writes through one layer — prefer the existing "
            "`project-knowledge-service` facade and delete the `useDataProvider` path, or the reverse — "
            "and do not keep both."
        ),
    ),
    dict(
        id="FE-03",
        title="The message store never evicts a conversation and three exported selectors are dead duplicates",
        sev="high",
        area="frontend",
        labels=["performance", "tech-debt"],
        effort="S",
        problem=(
            "The Zustand message store holds a `Map` of every conversation ever opened and nothing ever "
            "evicts an entry: `clear(convId)` exists but has zero callers repo-wide, `resetAll()` only "
            "fires on an `authority_generation` change, and the realtime hook deliberately skips the "
            "reset when a warm cache exists. Three exported selectors are also dead duplicates of a "
            "`useSyncExternalStore` twin, and the port subscribes unselected so every `set()` notifies "
            "all subscribers."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:37-193` — a Zustand store keyed by `convId` with no eviction bound.",
            "`frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:182-190` — `clear(convId)` has zero callers; a grep for `.clear(`/`resetAll(` across `conversations/**` finds exactly one caller, `conversations/reset-runtime.ts:17 → resetAll()`.",
            "`frontend/src/components/atomic-crm/conversations/presentation/use-conversation-realtime.ts:80-86` — switching conversations deliberately skips the reset when a warm cache exists (`if (!existing || existing.byId.size === 0) resetMessages(...)`).",
            "`frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:204-258` — `useConversationMessages` `:204`, `useConversationFlags` `:214` and `getNewestRealMessageId` `:246` have no importers; the live equivalents are re-implemented on `useSyncExternalStore` in `conversations/presentation/conversation-message-state.ts:1-82`.",
            "`frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts:197` — the port uses the unselected `subscribe`, so every `set()` notifies all subscribers.",
        ],
        impact=(
            "A recruiter who opens 500 conversations in a shift holds ~10k message objects plus "
            "per-conversation Maps for the tab's lifetime — combined with `gcTime: 24h` in "
            "`root/reset-runtime-state.ts` a long-lived tab never returns memory. Two copies of the "
            "selector logic also mean a `sortedCache` fix can be applied to the wrong one."
        ),
        fix=(
            "Call `clear(convId)` when the active conversation changes past a small LRU bound (keep the "
            "last ~5), or drop the cache-persistence feature and reset on switch. Delete "
            "`message-store.ts:200-258` and `getNewestRealMessageId`, keeping `useMessageStore` + "
            "`conversationMessageStatePort`, and move selection into the store or use "
            "`subscribeWithSelector` to cut notification fan-out."
        ),
    ),
    dict(
        id="FE-04",
        title="Four overlapping 30-second polls of the same needs-attention endpoint per open tab",
        sev="high",
        area="frontend",
        labels=["performance", "reliability"],
        effort="S",
        problem=(
            "Four queries poll the same `/conversations/needs-attention` endpoint every 30 seconds while "
            "the inbox is open: one unscoped count, three provider-scoped ones mounted inside the list "
            "panel, and a fourth gated on the popover. The query-key namespace is overloaded — element "
            "2 is a provider string in one caller and the literal `\"rows\"` in another — and no caller "
            "invalidates, so each re-polls blindly."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/layout/topbar/useNotifications.ts:16-24` — `queryKey: [\"conversations-needs-attention\"]` with `refetchInterval: 1000 * 30`.",
            "`frontend/src/components/atomic-crm/conversations/ChannelAdapterSelector.tsx:39-47` — three provider-scoped polls on `[\"conversations-needs-attention\", provider]`, each at 30 s, mounted inside the inbox list panel (`conversations/presentation/ConversationList.tsx:498`).",
            "`frontend/src/components/atomic-crm/layout/topbar/useNeedsAttention.ts:27-36` — a fourth poll on `[\"conversations-needs-attention\", \"rows\"]`, gated on the popover being open.",
            "The key collision is real, not dead code: `useNeedsAttention.ts:28` vs `ChannelAdapterSelector.tsx:40` disagree on element 2 of the same namespace.",
            "`frontend/src/components/atomic-crm/layout/topbar/useNotifications.test.ts:16-20` — the 30 s contract is pinned by a test, so this is intentional rather than accidental; it was simply never consolidated.",
        ],
        impact=(
            "4 requests per 30 s per open tab against a counting query, with the provider-scoped ones "
            "running for providers the user is not viewing — multiplied by every concurrent recruiter "
            "on a 2 vCPU / 4 GB droplet."
        ),
        fix=(
            "Consolidate into one `useAttentionCounts()` returning `{total, byProvider}` from a single "
            "query — the backend already supports `channel_provider`, so one unfiltered call plus "
            "client-side bucketing replaces three — raise the interval to 60 s, or drive it from the "
            "socket's `message.created` event since the socket is already connected on this screen. "
            "Update `useNotifications.test.ts` to the new contract."
        ),
    ),
    dict(
        id="FE-05",
        title="React.memo on the inbox row is structurally defeated by per-render row allocation",
        sev="high",
        area="frontend",
        labels=["performance"],
        effort="M",
        problem=(
            "`ConversationList` builds `rows` by allocating a new object per conversation inside a "
            "`useMemo` whose deps include `adapterPresentations`, `snippets`, `deferredQuery` and "
            "`readIds`, so every rebuild changes the identity of every `conversation` prop. "
            "`ConversationListItem` is `memo(...)` and its comment claims memo protects against exactly "
            "the three cases — typing in search, marking another row read, a sibling's realtime update "
            "— where `rows` is rebuilt and the shallow compare always fails."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:448-474` — `rows` allocates `{...c, _presentation, _snippet}` per conversation inside the `useMemo`, whose deps are `[adapterPresentations, conversations, snippets, deferredQuery, readIds]`.",
            "`frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:137-140` — `ConversationListItem` is `memo(...)`, with the memo rationale asserted in the comment at `:132-136`.",
            "`frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:438-445` — `snippets` is replaced wholesale on every list fetch via `setSnippets((prev) => ({...prev, ...snips}))`.",
            "`frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx:607` — `pendingReadIds` is a new `Set` on each open and is also passed into the sort comparator at `:473`.",
            "Avatar and unread styles were carefully hoisted at `:68-115` to avoid allocation, so the remaining per-row allocation is an oversight rather than a design choice.",
        ],
        impact=(
            "On a 25-row list every deferred keystroke rebuilds 25 objects, re-sorts, and re-renders 25 "
            "memo'd components that then fail to skip. This is client-side only, but it is the "
            "most-touched screen in the product and low-end Android recruiters are the target."
        ),
        fix=(
            "Split the row view-model: keep `rows` as the raw `conversations` array and pass "
            "`presentation`/`snippet` as separate props pulled from a per-id `Map<convId, rowVM>` cache "
            "memoized on `conversationIdsKey`, so identity is stable while inputs are unchanged. Pass "
            "the single `isRead: boolean` for a row instead of the whole `readIds` set, so read state "
            "cannot invalidate row identity."
        ),
    ),
    dict(
        id="FE-06",
        title="Confirmed-dead i18n catalog blocks and four self-testing kit/ components",
        sev="medium",
        area="frontend",
        labels=["tech-debt", "documentation"],
        effort="S",
        problem=(
            "`vietnameseCrmMessages.ts` still ships `resources.{companies,deals,notes,tasks,tags}`, "
            "`crm.settings.*`, a large `crm.dashboard.*` block and `crm.image_editor`/`crm.header`/"
            "`crm.profile.*`, and per-key greps find no reference outside the catalog file. Separately, "
            "`kit/StatCard`, `kit/DataTableCard`, `kit/AlternateCard` and `kit/KitSidebar` have no "
            "consumers outside their own test files — one test even asserts `AlternateCard` must not be "
            "used — so ~1,000 LOC of components and tests exist only to test themselves."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:79-175` — `resources.companies` `:79`, `.deals` `:83`, `.notes` `:87`, `.tasks` `:91`, `.tags` `:95`, `crm.settings.companies/deals/notes/tasks` `:154-175`.",
            "`frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:120-136` (`crm.dashboard.*`), `:188-193` (`crm.image_editor`), `:137` (`crm.header`), `:195` (`crm.profile.inbound/mcp`) — no reference outside the catalog.",
            "`frontend/src/components/atomic-crm/kit/index.ts:11-23` — exports `StatCard`, `AlternateCard`, `KitSidebar` and `DataTableCard`, all with no consumer outside their own tests.",
            "`frontend/src/components/atomic-crm/users/account-layout-regressions.test.ts:11-16` — the test actively asserts `AlternateCard` is *not* used, so a regression test is the only thing keeping the component alive.",
            "Live and must be kept: `kit/PageShell`/`PageHeading`/`EmptyState` (`automation/BotRunList.tsx:6`, `knowledge-base/*`, `users/*`), `misc/LoadingState` (`conversations/presentation/ChatThread.tsx:38`) and `misc/Markdown` (`knowledge/StoredKnowledgePanel.tsx:15`).",
        ],
        impact=(
            "~100 LOC of unreachable translation keys and ~1,000 LOC of unused-but-tested components "
            "inflate the review surface and train readers to think the design system has consumers it "
            "does not."
        ),
        fix=(
            "Delete the unreferenced `crm.*`/`resources.*` blocks from `vietnameseCrmMessages.ts`, and "
            "delete `kit/{stat-card,data-table-card,sidebar}.tsx` plus the `AlternateCard` export and "
            "their four test files — or wire them into the pages that currently hand-roll the same "
            "chrome. Update whatever doc lists contacts/cases/workflows as dormant."
        ),
        notes=(
            "The `contacts/`, `cases/`, `workflows/`, `deals/`, `companies/`, `notes/` and `tasks/` "
            "features are **already deleted** — there are no such directories, "
            "`capabilities/kernel/index.tsx:165-230` registers exactly 8 resources and "
            "`capabilities/static-recruitment-runtime.ts:19-28` is the authoritative id list. The doc "
            "that lists them as dormant is wrong today; fix the doc, do not open a deletion ticket. "
            "`admin/*-guesser.tsx` (`edit/list/show`) is suspect RA scaffolding, not confirmed dead — "
            "grep its consumers first. `automation/` is live (registered as `kernel.resource.bot-runs` "
            "at `capabilities/kernel/index.tsx:172-179`)."
        ),
    ),
    dict(
        id="FE-07",
        title="Product code hardcodes Vietnamese, bypassing a catalog served by two competing providers",
        sev="medium",
        area="frontend",
        labels=["tech-debt"],
        effort="M",
        problem=(
            "Every product god component hardcodes Vietnamese in JSX and never calls `useTranslate`, "
            "while `components/admin/` uses it in 20+ files. Action labels are duplicated with two "
            "different ellipsis glyphs, and two i18n providers exist: an English default that the "
            "runtime always overrides with the Vietnamese one, so `admin/` leaks English strings into "
            "a Vietnamese UI."
        ),
        evidence=[
            "`useTranslate` appears in only 2 product files — `conversations/presentation/ChatThread.tsx:374` and `integrations/ZaloIntegrationPage.tsx:974` — versus 20+ files under `components/admin/`.",
            "Hardcoded Vietnamese in JSX: `dashboard/RecruitingCommandCenter.tsx:184,277-279,337-339`; `conversations/presentation/ConversationList.tsx:265-281`; `performance/PerformancePage.tsx:45-47,113-118,150-190`; `personas/PersonaList.tsx:44-46,66-90`; `integrations/ZaloIntegrationPage.tsx:1908-1920,2010-2020`.",
            "Duplicated literals in three inconsistent forms: `\"Đang lưu…\"` (U+2026) at `dashboard/CandidateDataDialog.tsx:375`, `conversations/ConversationContextPanel.tsx:461`, `knowledge/KnowledgeSourceEdit.tsx:143` and `integrations/FacebookMessengerPageCard.tsx:110`; `\"Đang lưu...\"` (three dots) at `personas/PersonaForm.tsx:596`; and bare `\"Đang lưu\"` with no punctuation at `integrations/ZaloIntegrationPage.tsx:1914` and `:2014`. The same split exists for `\"Lưu thay đổi\"` (≥4 sites) and `\"Thử lại\"` (≥5 sites).",
            "`frontend/src/lib/i18nProvider.ts` is an English polyglot provider imported only as the default at `components/admin/admin.tsx:9`, while `App.tsx:3` and `components/atomic-crm/root/CRM.tsx:73` always supply the Vietnamese one.",
            "`frontend/src/components/admin/filter-form.tsx:408` renders English \"Save current query...\" inside the Vietnamese UI because `ra.saved_queries.*` has no catalog entry (`saved-queries.tsx:75` has the same gap).",
        ],
        impact=(
            "Two ellipsis glyphs and four copies of every action label make a wording fix an O(n) source "
            "edit, and `admin/` shows English micro-copy inside a Vietnamese product UI."
        ),
        fix=(
            "Add the ~40 missing micro-copy keys to `vietnameseCrmMessages` (`common.save_changes`, "
            "`common.retrying`, `common.retry`, `common.loading`, `common.load_failed`, "
            "`common.unsaved_changes`), move product strings onto `useTranslate`, and delete "
            "`frontend/src/lib/i18nProvider.ts` in favour of the Vietnamese provider as the admin "
            "default."
        ),
    ),
    dict(
        id="FE-08",
        title="The no-explicit-any rule is enforced only for flat globs and never for atomic-crm",
        sev="medium",
        area="frontend",
        labels=["tech-debt"],
        effort="S",
        problem=(
            "`no-explicit-any` is set to `error` only for three flat globs, so "
            "`src/components/admin/layout/**` and `src/components/admin/form/**` are not covered, and "
            "31 files inside the covered set neutralise the rule with a file-level disable. "
            "`src/components/atomic-crm/**` — 62k LOC of product code — has no rule at all, and the two "
            "`as unknown as` casts on `useDataProvider()` sit at the exact seam where conversation "
            "mutations are dispatched."
        ),
        evidence=[
            "`frontend/eslint.config.js:56-62` — `@typescript-eslint/no-explicit-any: error` is applied to a flat-glob file set (admin/, hooks/, lib/), which does not reach nested admin subdirectories.",
            "31 admin files disable the rule at file level (`admin/autocomplete-input.tsx:1`, `admin/boolean-input.tsx:1`, `admin/bulk-delete-button.tsx:1`, `admin/edit-guesser.tsx:1`, `admin/filter-form.tsx:1`, `admin/list-guesser.tsx:1`, `admin/image-field.tsx:1`, `admin/number-field.tsx:1`, `admin/record-field.tsx:1`, …) plus ~20 line-level disables.",
            "`frontend/src/components/atomic-crm/**` is unguarded by any no-any rule; in practice it is clean — a `: any|as any|as unknown as|@ts-ignore|@ts-expect-error` grep over the product tree returns only 4 real sites, the rest being test-only fetch mocks.",
            "`frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:371` and `conversations/presentation/use-conversation-actions.ts:48` — the two `as unknown as` casts bypass the typed `CrmDataProvider` contract.",
            "4 `@ts-expect-error` remain, all in admin/: `file-field.tsx:49`, `image-field.tsx:42`, `reference-array-field.tsx:135`, `reference-many-field.tsx:105`; there are zero `@ts-ignore`/`@ts-nocheck` in the tree.",
        ],
        impact=(
            "The stated standard (\"no any in admin/, hooks/, lib/\") is met only in the letter, since "
            "the disables are explicit, and is unenforced for three quarters of the codebase. The two "
            "`as unknown as` casts bypass the typed provider contract where conversation mutations are "
            "dispatched."
        ),
        fix=(
            "Change the globs to `**` form (`src/components/admin/**/*.{ts,tsx}`) and move the shared "
            "no-any set into the root config. Replace the two `as unknown as` casts with a properly "
            "typed `CrmDataProvider` that includes `setConversationMode`/`sendConversationReply`, and "
            "either type the RA guesser files out or delete them after checking consumers."
        ),
    ),
    dict(
        id="FE-09",
        title="ExternalSourceList hand-rolls a 466-poll, 3h40m polling state machine",
        sev="medium",
        area="frontend",
        labels=["performance", "reliability"],
        effort="M",
        problem=(
            "`ExternalSourceList` derives a 13,200,000 ms (3h40m) sync budget and turns it into 466 "
            "follow-up polls, then implements them with 11 `useRef` plus 4 `useState`: a generation "
            "guard, an abort controller, a `PollSession` with per-row baseline signatures, a `loadRef` "
            "trampoline, a refresh-signal replay guard and a cooldown timer. There is no "
            "`document.visibilityState` gate anywhere, so polling continues in background tabs."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:27-36` — `SINGLE_PAGE_SYNC_MAX_POLL_MS` = 4×30 min + 3×(2000 s) = 13,200,000 ms and `MAX_FOLLOW_UP_POLLS` = 30 + ceil((13.2M − 120k)/30k) = 466.",
            "`frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:231-235` — the first 30 polls run at 4 s, then 30 s each, and the session stops only when `attempts >= MAX_FOLLOW_UP_POLLS`.",
            "`frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:182-197` — 11 `useRef` + 4 `useState` implementing the generation guard, abort controller, per-row baseline signatures, `loadRef` trampoline (`:246`, assigned `:296`), refresh-signal replay guard (`:194`, `:325-343`) and cooldown timer (`:355-359`).",
            "No `document.visibilityState` check exists in the file, so the loop runs regardless of whether anyone is looking at the page.",
        ],
        impact=(
            "A single open project page issues up to 466 list requests over ~3.7 h, each rendering a "
            "full `useState` row array — the most server-hostile frontend loop in the repo against a "
            "2 vCPU box, wrapped in a 466-iteration state machine that is effectively unreviewable."
        ),
        fix=(
            "Replace with `useQuery({queryKey: [\"external-sources\", projectId, variant], refetchInterval: "
            "(q) => nextPollDelay(q.state.data)})` — TanStack already pauses on "
            "`refetchIntervalInBackground: false` and exposes `isFetching`. Keep the pure helpers as "
            "`projects/domain/externalSourceRow.ts` (`rowProgressSignature` `:129`, `statusDotClass` "
            "`:68`, `formatTimestamp` `:86`, `truncate` `:126`) and move the table to "
            "`presentation/ExternalSourceRow.tsx`, leaving a ~120-LOC component."
        ),
    ),
    dict(
        id="FE-10",
        title="A module-scope socket port pulls socket.io-client into the entry chunk and never re-auths after JWT rotation",
        sev="medium",
        area="frontend",
        labels=["performance", "reliability"],
        effort="S",
        problem=(
            "`createLeadRealtimePort(getRealtimeSocket())` is evaluated at module scope in a file that "
            "the entry graph imports eagerly, so the `realtime-vendor` chunk is fetched on first paint "
            "even though the port is only needed inside the inbox. The same socket also reads the JWT "
            "only when a connection attempt starts, so a long-lived socket keeps its original token "
            "after a mid-session refresh."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/capabilities/recruitment/index.tsx:32` — `const leadRealtimePort = createLeadRealtimePort(getRealtimeSocket());` at module scope, evaluating at import time before any conversation is opened.",
            "`frontend/src/components/atomic-crm/providers/realtime/realtime-socket.ts:21-33` — `getRealtimeSocket()` constructs the Manager even with `autoConnect` false, so the module graph determines the chunk.",
            "`frontend/src/components/atomic-crm/capabilities/recruitment/index.tsx` is imported eagerly via `capabilities/static-recruitment-runtime.ts:1-2` → `root/reset-runtime-state.ts:6-10` → `App.tsx:6`/`installation/InstallationBootstrap.tsx`, so `vite.config.ts`'s `realtime-vendor` split does not keep socket.io-client off first paint.",
            "`frontend/src/components/atomic-crm/providers/realtime/realtime-socket.ts:23-25` — the JWT is read in the socket `auth` callback only when a connection attempt starts, while `lib/apiClient.ts:161-176` (`refreshOnce()`) rotates the token. [INFERRED — the backend's re-authorisation of an already-open socket was not verified.]",
            "Teardown on logout is correct: `providers/rest/authProvider.ts:97-102` calls `closeRealtimeSocket()`.",
        ],
        impact=(
            "Entry-bundle bytes are spent on a library only needed inside the inbox, plus a silent "
            "\"no realtime after token rotation\" failure mode whose symptom (missing lead updates) is "
            "indistinguishable from a backend bug."
        ),
        fix=(
            "Convert `leadRealtimePort` into a lazily-created getter inside "
            "`RecruitmentConversationContext`, and lazy-load `Dashboard` (which already owns the only "
            "`react-virtuoso` usage). For the token, emit a socket re-auth "
            "(`socket.disconnect().connect()` or an `auth.refresh` event) when `refreshOnce()` succeeds."
        ),
    ),
    dict(
        id="FE-11",
        title="Two virtualization libraries, and manualChunks still splits the legacy one",
        sev="medium",
        area="frontend",
        labels=["performance", "tech-debt"],
        effort="M",
        problem=(
            "`manualChunks` gives `/react-virtuoso/` its own vendor chunk, but the inbox thread uses "
            "`virtua` and react-virtuoso survives in exactly one place, so the config spends a manual "
            "split on the legacy library while the library actually on the hot path has no chunk rule. "
            "`zod` also reaches the eager graph with no chunk rule."
        ),
        evidence=[
            "`frontend/vite.config.ts:119-120` — `manualChunks` maps `/react-virtuoso/` to `virtuoso-vendor`.",
            "`frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:14` — the inbox thread uses `virtua` (`VList`), which is absent from `manualChunks` and therefore lands in whichever chunk imports it (the `conversations` resource chunk).",
            "`frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.tsx:5` — `GroupedVirtuoso` from react-virtuoso is the single remaining usage of the legacy library.",
            "`zod` reaches the eager graph via `InstallationBootstrap → root/runtime-manifest.ts:13-18 → runtime-manifest-policy.ts:1` and has no chunk rule.",
            "Correct and deliberate elsewhere, so do not disturb it: `misc/Markdown.tsx:15-18` dynamic-imports `marked` + `dompurify`, and every resource entry is `lazy()` (`conversations/index.tsx`, `personas/index.tsx`, `projects/index.tsx`, `knowledge*/index.tsx`, `users/index.tsx`, `automation/index.tsx`, `integrations/index.tsx:4-8`).",
        ],
        impact=(
            "Two virtualization libraries are maintained for one list each (~30–50 KB combined), and "
            "the stale chunk rule means the split config no longer describes reality, so future bundle "
            "analysis will mislead."
        ),
        fix=(
            "Pick one list virtualizer — `virtua` is already the hot path, so migrate "
            "`RecruitingCommandCenter` and drop `react-virtuoso` — and update `manualChunks` in "
            "`frontend/vite.config.ts` to name `virtua` and `zod`, with a comment that the rule set "
            "must track imports."
        ),
    ),
    dict(
        id="FE-12",
        title="A 24-hour gcTime with no persister, plus offlineFirst mutations that can replay",
        sev="medium",
        area="frontend",
        labels=["reliability", "performance"],
        effort="S",
        problem=(
            "Every runtime generation configures `staleTime: 30_000`, `gcTime: 24h` and "
            "`networkMode: \"offlineFirst\"` on both queries and mutations, but no persister is wired "
            "up even though two persister packages are declared. With `offlineFirst`, a mutation "
            "attempted with no network is held in the mutation cache indefinitely and replayed on "
            "reconnect — for a chat product that is a duplicate-send and out-of-order-mode risk."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/root/reset-runtime-state.ts:41-52` — `staleTime: 30_000`, `gcTime: 1000 * 60 * 60 * 24`, `networkMode: \"offlineFirst\"` on queries and `networkMode: \"offlineFirst\"` on mutations.",
            "`frontend/package.json:48,51` — declares `@tanstack/query-async-storage-persister` and `@tanstack/react-query-persist-client`, but no file in `src` imports them, so the 24 h `gcTime` retains memory in-tab and buys nothing across reloads.",
            "The replay risk applies to `sendConversationReply`, `markConversationAsRead` and `setConversationMode`. [INFERRED — the offline replay path was not traced end-to-end; the server's `send_unknown` guard may absorb it.]",
            "Per-feature keys are otherwise disciplined and complete (`[\"facebook-integration-status\"]`, `[\"facebook-credentials\"]`, `[\"facebook-page-projects\", pageId]`, `[\"knowledge-units\", sourceId]`, `[\"performance-metrics\", window]`, `ATTENTION_QUERY_KEY`/`CANDIDATES_QUERY_KEY`), and `dashboard/RecruitingCommandCenter.tsx:104-118` documents a correct intentional `staleTime 25s < refetchInterval 30s` pairing — not a defect.",
        ],
        impact=(
            "A long-lived tab holds every response ever fetched, and an offlineFirst mutation on a "
            "flaky Zalo or recruiter network can be replayed after the user believes it failed."
        ),
        fix=(
            "Drop `gcTime` to the 5-minute default unless persistence is actually implemented; either "
            "implement the persister (the deps are already declared) or remove both packages. Consider "
            "`networkMode: \"online\"` for chat mutations and keep the server's `send_unknown` as the "
            "duplicate guard."
        ),
    ),
    dict(
        id="FE-13",
        title="The layered slice pattern covers 6 of ~22 features, and the two worst god files are unlayered",
        sev="medium",
        area="frontend",
        labels=["tech-debt"],
        effort="L",
        problem=(
            "`application`/`domain`/`infrastructure` folders exist only under six features, while "
            "sixteen others — including `integrations/` and `dashboard/` — are flat, so the two worst "
            "god files are exactly the two features that never got the pattern. Two compat re-export "
            "shims from an in-flight migration are also still standing, and feature tests sit at "
            "feature root rather than beside the code they cover."
        ),
        evidence=[
            "Layered: `conversations/`, `leads/`, `projects/`, `personas/`, `knowledge/`, `reporting/` — 6 of ~22 features.",
            "Flat (no layers): `integrations/`, `dashboard/`, `performance/`, `users/`, `knowledge-base/`, `automation/`, `settings/`, `layout/`, `misc/`, `kit/`, `root/`, `capabilities/`, `installation/`, `login/`, `providers/`, `hooks/`.",
            "`frontend/src/components/atomic-crm/conversations/conversation-list-filters.ts:1-15` re-exports from `domain/conversation-list-filters.ts`, and `conversations/presentation/use-conversation-realtime.ts:32-36` re-exports `messageOrdering` — migration residue, not duplication.",
            "Tests live outside the slices: `conversations/conversationDisplay.test.ts`, `conversations/chatRepository.test.ts`, `conversations/candidateNotes.test.ts` at feature root.",
        ],
        impact=(
            "The pattern was not applied where it was needed most, so the two largest components have "
            "no domain/application seam to extract along and no consistent home for pure logic or its "
            "tests."
        ),
        fix=(
            "Declare the rule in the folder context doc and either apply or drop it. At minimum give "
            "`integrations/` and `dashboard/` domain/application/infrastructure folders while executing "
            "FE-01 and FE-02, and finish the two re-export shims by updating the ~6 importers and "
            "deleting them."
        ),
        notes=(
            "Layering in the direction that was audited is verified clean and is **not** a ticket: "
            "`components/ui/**` imports nothing from `components/admin/**` or `components/atomic-crm/**`; "
            "`components/admin/**` imports nothing from `atomic-crm` and depends only on `ui` + `lib` + "
            "`ra-core`; `src/lib/**` and `src/hooks/**` import no feature code (`ui/sidebar.tsx:7` "
            "imports only `@/hooks/use-mobile` + `@/lib/utils`); product code stays inside `atomic-crm/` "
            "with only the app shell (`main.tsx:6`, `App.tsx:1-6`) as an outside consumer."
        ),
    ),
    dict(
        id="FE-14",
        title="Duplicated credential-field machinery between the Zalo and Facebook pages",
        sev="medium",
        area="frontend",
        labels=["tech-debt"],
        effort="M",
        problem=(
            "Two masked-secret-with-reveal implementations exist — `CredentialSecretField` for Zalo "
            "(copy + reveal + status) and an inline `MetaAppSecretField` for Facebook (reveal only, "
            "`readOnly` when revealed, different placeholder semantics) — and the two pages disagree on "
            "the data-access idiom for the same kind of screen. Every credential-policy change must be "
            "made twice, and one of the two has no test for copy/reveal parity."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/integrations/CredentialSecretField.tsx:28-103` — the Zalo masked-secret field with copy, reveal and status.",
            "`frontend/src/components/atomic-crm/integrations/FacebookMessengerIntegrationPage.tsx:110-190` — `MetaAppSecretField` (reveal only, `readOnly` when revealed) and `:80-107` `MetaAppPlainField` for non-secret fields; both share `SettingsFieldStatus` but neither reuses the other's field shell.",
            "Idiom mismatch: Facebook uses `useQuery` at `:223`, `:245`, `:352`, `useGetList` at `:230` and `useMutation` at `:251`/`:361`/`:375` with `invalidateQueries` at `:265`/`:386`; Zalo uses `zaloIntegrationGateway` + `useState` with a manual reload (`integrations/ZaloIntegrationPage.tsx:1014-1063`).",
            "OAuth callback handling is factored out correctly (`integrations/facebook-oauth-callback.ts`, imported at `FacebookMessengerIntegrationPage.tsx:36`) — a good precedent for the rest of the extraction.",
        ],
        impact=(
            "Every credential-policy change (masking rules, reveal-on-demand, \"blank means keep\", "
            "clipboard behaviour) must be made in two places, and one of the two has no test for "
            "copy/reveal parity."
        ),
        fix=(
            "Generalise `CredentialSecretField` into an `admin/`-level `SecretField` + `PlainField` pair "
            "with a `reveal?: () => Promise<string | null>` prop, delete `MetaAppSecretField` and "
            "`MetaAppPlainField`, and move the Zalo page's load/save/test onto TanStack Query using the "
            "key conventions Facebook already uses."
        ),
    ),
    dict(
        id="FE-15",
        title="Dashboard derivations are recomputed on every render",
        sev="medium",
        area="frontend",
        labels=["performance"],
        effort="S",
        problem=(
            "`RecruitingCommandCenter` runs `filterHumanInterventions`, `groupCandidatesByDay` and a "
            "`reduce` count inline on every render, including opening or closing the candidate dialog "
            "whose state lives in the same component subtree, every 30 s refetch, and every "
            "`isFetching` toggle. The grouping is non-trivial and runs over the whole candidate list, "
            "and `GroupedVirtuoso` depends on its output."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.tsx:149-150` — `filterHumanInterventions(data?.immediate ?? [])` and `groupCandidatesByDay(candidatesQuery.data ?? [])` are plain statements in the render body.",
            "`frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.tsx:556` — the candidate dialog's open/close state lives in the same component, so unrelated UI events re-run both derivations.",
            "`frontend/src/components/atomic-crm/dashboard/candidateDashboard.ts:187-191` — `groupCandidatesByDay` maps and groups the entire candidate list; `RecruitingCommandCenter.tsx:5` `GroupedVirtuoso` consumes those groups.",
            "Contrast with `deriveCacheDiscriminators` (`dashboard/recruitingCommandCenterLogic.ts`), which is already extracted, pure and consumed at `RecruitingCommandCenter.tsx:163`.",
        ],
        impact=(
            "O(n) grouping plus filter plus sort is re-executed for unrelated UI events; with a large "
            "candidate list that is visible jank on the landing page."
        ),
        fix=(
            "`useMemo` both derivations on `[data?.immediate]` / `[candidatesQuery.data]` and hoist the "
            "count into the same memo. Also stop `saveCandidateProfile` "
            "(`RecruitingCommandCenter.tsx:119`) refetching on the failure path, which doubles list "
            "traffic on every failed edit."
        ),
    ),
    dict(
        id="FE-16",
        title="Unreachable English i18n default, unused dependencies, and an unscoped global CSS surface",
        sev="low",
        area="frontend",
        labels=["tech-debt", "documentation"],
        effort="S",
        problem=(
            "`frontend/src/lib/i18nProvider.ts` is an English default that the runtime always overrides, "
            "so \"which locale am I in\" has two answers. Four declared dependencies have no importers, "
            "and the CSS surface is one 48 KB global sheet plus ~19 feature stylesheets that are not "
            "actually scoped by module because their selectors nest under a shared global container "
            "class."
        ),
        evidence=[
            "`frontend/src/lib/i18nProvider.ts` is imported as the default at `components/admin/admin.tsx:9`, but `App.tsx:3` and `components/atomic-crm/root/CRM.tsx:73` always supply the Vietnamese provider, making the English default unreachable in production.",
            "`frontend/package.json:48,51,55,61` — `@tanstack/query-async-storage-persister`, `@tanstack/react-query-persist-client`, `diacritic` and `qs` have no importers in `src`; `lib/vietnameseSearch.ts` implements its own normalisation and query strings use `URLSearchParams`.",
            "`frontend/src/index.css` is 49,208 bytes (48.1 KB) and `conversations/inbox/` holds 19 stylesheets (`chat.css` 32.6 KB, `features.css` 30.9 KB, `untitledui-conversations.css` 21.7 KB, `personas-studio.css` 19.7 KB, `tokens.css` 13.3 KB), plus `integrations/settings.css` 37.8 KB, `projects/projects.css` 30.2 KB and `performance/performance.css` 27.7 KB.",
            "Selectors are nested under a global container class rather than scoped per module — `conversations/inbox/chat.css` alone has 170 `inbox-bg-container` rules (`.inbox-bg-container .bubble` at `:996`) and `context-drawer.css` has 145, including `.inbox-bg-container .candidate-info-row[data-field=\"notes\"]` at `:741`.",
            "Positive signs to preserve: the hoisted `--tt-*` token bridge in `kit/tailkit-system.css`, `contain: layout style paint` at `conversations/inbox/chat.css:967`, `:1007` and `:1021`, and the dedicated CSS regression tests.",
        ],
        impact=(
            "Four packages of audit and `npm ci` surface buy nothing, the locale question has two "
            "answers, and feature CSS remains reachable by any global rule."
        ),
        fix=(
            "Delete `frontend/src/lib/i18nProvider.ts` (or make the admin default Vietnamese), remove "
            "the four confirmed-unused dependencies after checking `scripts/` and `*.mjs` hooks, and "
            "scope the feature stylesheets under a per-module container class instead of the shared "
            "`.inbox-bg-container`."
        ),
    ),
    dict(
        id="TEST-01",
        title="CI and the deploy gate run 1 of 29 backend integration test files",
        sev="critical",
        area="testing",
        labels=["testing", "ops"],
        effort="M",
        problem=(
            "The integration lane is 29 files wide, but both CI and the local release gate invoke "
            "exactly one of them — the harness smoke test that only proves the lane works. Every "
            "concurrency, crash-window, migration-roundtrip and token-binding invariant the team "
            "deliberately wrote is therefore unenforced at merge time."
        ),
        evidence=[
            "`.github/workflows/quality-gates.yml:103` — `pytest -m integration tests/integration/test_harness_smoke.py`.",
            "`Makefile:21` — `release-check` uses the identical single-file invocation, and `Makefile:37/54/60` deploy targets depend on `release-check`.",
            "`backend/tests/integration/` contains 29 test files; the 28 that never run include `test_outbound_finalize_lock_race.py` (the actual \"Đã chặn\" production bug — `finalize_outbound_dispatch` clearing a live turn's lock), `test_outbound_crash_window.py`, `test_delivery_receipt_send_unknown.py`, `test_facebook_lifecycle.py`, `test_canonical_channel_identity_migration.py` and `test_project_category_activation.py` (~1,000 lines of category cutover, rollback and snapshot).",
            "`backend/tests/integration/test_harness_smoke.py:17-63` proves only that the lane works, not that the application does.",
        ],
        impact=(
            "A PR touching `backend/app/services/outbox_service.py`, `app/services/conversation/bot_path.py` "
            "or any migration merges and deploys green with those invariants broken."
        ),
        fix=(
            "Change `.github/workflows/quality-gates.yml:103` to `pytest -m integration` (all files) and "
            "make the same change in `Makefile:21`. Raise that job's `timeout-minutes` from 20 to 40–45 "
            "— each `_alembic()` call spawns a subprocess with `timeout=120` "
            "(`backend/tests/integration/conftest.py:64-76`) and the migration tests chain several per "
            "test — and add `--durations=25` so the slow lanes stay visible. Keep the smoke file as a "
            "fast first step."
        ),
    ),
    dict(
        id="TEST-02",
        title="Knowledge-ingestion tests are marked skip, not integration, so they run nowhere",
        sev="critical",
        area="testing",
        labels=["testing"],
        effort="M",
        problem=(
            "Three knowledge-ingestion test modules carry an unconditional `pytest.mark.skip` with the "
            "reason \"moved out of unit suite\", which is false — they were not relocated. Because the "
            "marker is `skip` and not `integration`, they do not run under `-m integration` either, so "
            "the pipeline that produces every RAG answer is untested in production shape."
        ),
        evidence=[
            "`backend/tests/test_product_features.py:22-25` — module-level `pytest.mark.skip(reason=\"integration test: needs live DB + fixtures (moved out of unit suite)\")`, killing all ~10 tests.",
            "`backend/tests/test_knowledge.py:15-20` — the same pattern, killing all 4 tests.",
            "`backend/tests/test_knowledge_pipeline.py:35-37` — `_integration_skip = pytest.mark.skip(...)` applied to `test_pipeline_run_writes_rich_chunks`, `test_pipeline_run_marks_flagged_low_confidence`, `test_pipeline_retries_on_malformed_then_succeeds` (`:351`) and `test_pipeline_raises_after_retry_failure` (`:368`).",
            "`backend/tests/test_knowledge_pipeline.py:351-365` — the malformed-LLM-JSON retry branch asserts `calls[\"n\"] == 2` then `doc.status == APPROVED`, and never executes.",
            "`backend/tests/test_product_features.py:125-137` — the 16-row `extract_product_features` invariant, and re-run idempotency at `:167-179`, are likewise dead source text.",
        ],
        impact=(
            "The branch handling an LLM that returns malformed JSON during ingestion, the feature-"
            "extraction invariant and ingestion idempotency all exist only as source text, so a "
            "regression in the RAG ingestion pipeline ships undetected."
        ),
        fix=(
            "Convert these to `pytest.mark.integration` and move them under "
            "`backend/tests/integration/` so they inherit the disposable-DB fixtures; the "
            "`db_session`/`clean_kb`/`clean_features` fixtures (`test_product_features.py:91-102`) are "
            "trivially re-expressible against `integration_session`. TEST-01 then makes them actually "
            "run."
        ),
    ),
    dict(
        id="TEST-03",
        title="Backend coverage is never measured and the frontend 80% gate covers 3 of 425 files",
        sev="critical",
        area="testing",
        labels=["testing", "ops"],
        effort="M",
        problem=(
            "The backend has no coverage tooling at all: `pytest-cov` is not a dependency and no `--cov` "
            "flag appears anywhere in CI or the Makefile. The frontend's 80% gate is real but its "
            "`coverage.include` names exactly three paths, so the number reads as a project-wide gate "
            "while covering 3 of 425 files."
        ),
        evidence=[
            "`backend/pyproject.toml:60-67` — dev dependencies are `pytest`, `pytest-asyncio` and `ruff`; there is no `pytest-cov`, no `addopts`, and no `--cov` anywhere in CI or `Makefile`.",
            "`frontend/vitest.config.ts:19-23` — `coverage.include` is exactly `capabilities/kernel/index.tsx`, `integrations/CredentialSecretField.tsx` and `performance/PerformanceTrendChart.tsx`; `:26-31` sets flat 80% thresholds on lines, functions, branches and statements.",
            "`.github/workflows/quality-gates.yml:143` — runs `npm run test:unit:app:coverage:changed-surface -- --run`, so the 80% figure is presented as a CI gate.",
        ],
        impact=(
            "A change that guts `backend/app/graph/runner.py` (1,259 lines), "
            "`app/services/conversation/bot_path.py` (1,118 lines) or `app/services/outbox_service.py` "
            "produces no signal at all. On a 2 vCPU / 4 GB single droplet, untested hot paths are "
            "exactly where latency and correctness regressions land."
        ),
        fix=(
            "Add `pytest-cov` to the backend dev extra and run `--cov=app --cov-report=term-missing` in "
            "the `backend-unit` job — report-only at first, then a ratchet floor. Extend the frontend "
            "`include` to `src/components/atomic-crm/**` with a ratchet threshold rather than a flat "
            "80%, keep the 3-file contract as an additional strict sub-gate, and relabel the CI step so "
            "it does not read as whole-tree coverage."
        ),
    ),
    dict(
        id="TEST-04",
        title="The release gate is real but narrow, mislabelled correctness, and not wired to deploy",
        sev="high",
        area="testing",
        labels=["testing", "ops"],
        effort="M",
        problem=(
            "The golden-pass-rate gate is genuinely fail-closed and well unit-tested, but it measures "
            "retrieval precision on a committed fixture scored with canned embeddings — no bot turn is "
            "executed — while being labelled `correctness`. The latency SLO is disabled in CI so p95 and "
            "error-rate cannot block, and no job consumes the gate, so the deploy path can proceed "
            "while CI is red."
        ),
        evidence=[
            "`backend/app/services/release_gate.py:21` — `GOLDEN_PASS_RATE_THRESHOLD_PCT = 95.0`, with a fail-closed gate at `:171-176`; the logic is well unit-tested (`backend/tests/test_release_gate.py:70-135`, `test_release_gate_cli.py:50-99`).",
            "`.github/workflows/quality-gates.yml:233` — `RELEASE_GATE_LATENCY_SLO_ENABLED: \"false\"`, so `evaluate_release_gate` appends `latency_slo` to `not_evaluated` (`release_gate.py:156-166`) and the p95 and error-rate gates cannot block in CI.",
            "`.github/workflows/quality-gates.yml:260` — the golden artifact comes from `backend/scripts/benchmark_rag.py --gold --min-pass-rate 0`; in `--gold` mode (`backend/scripts/benchmark_rag.py:180-200`) that is the offline Vietnamese RAG gold set scored with canned embeddings from `tests/fixtures/rag_gold/embeddings.json`, computing precision@3/@5, recall@10 and MRR.",
            "`release-gate` has no `needs:` and no job consumes it; `Makefile:37/54/60` deploy targets depend on `release-check`, which re-runs the same benchmark locally and never checks CI status.",
        ],
        impact=(
            "It will block if gold-set retrieval precision drops below 95%, but it is called "
            "`correctness` (`GateFailure(gate=\"correctness\", ...)`) while testing retrieval, it never "
            "exercises the turn pipeline, and `make deploy` can proceed while CI is red. `--min-pass-rate "
            "0` also means the benchmark script itself can never exit non-zero."
        ),
        fix=(
            "Rename the gate to `retrieval_correctness` in `release_gate.py` and its failure detail; add "
            "a CI job running `scripts/smoke_turn.py` against a stubbed provider (it already fails "
            "closed on `--inject-failure`); make `release-check` require a green CI run for the commit "
            "under release (`gh run list --commit \"$(git rev-parse HEAD)\" --status success`); and "
            "either enable the latency SLO in CI with its 30-run window or document explicitly that "
            "latency is not release-gated."
        ),
        notes=(
            "The turn pipeline itself is genuinely well tested and is **not** a ticket: "
            "`backend/tests/test_graph_runner_turn.py` is 2,464 lines / ~60 behaviour tests, ownership "
            "and pre-send guards are covered by `test_concurrency.py:594-780`, "
            "`integration/test_outbound_finalize_lock_race.py` and `test_llm_semaphore.py:419-462`, and "
            "`scripts/smoke_turn.py` with `test_smoke_turn.py` is exactly the right shape for a "
            "pre-flip gate. The gap is that no CI gate runs any of it."
        ),
    ),
    dict(
        id="TEST-05",
        title="No contract test links the frontend data provider to the backend routes",
        sev="high",
        area="testing",
        labels=["testing"],
        effort="M",
        problem=(
            "The frontend data provider asserts hardcoded URL strings with no link to the backend, and "
            "the backend pins its route surface only against itself. A route rename, a prefix move or a "
            "resource-to-path remap therefore keeps both suites green while the console 404s."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/providers/rest/dataProvider.test.ts:62` — `expect(url).toContain(\"/api/v1/leads?\")`, a hardcoded string with no link to the backend.",
            "`frontend/src/components/atomic-crm/providers/rest/dataProvider.test.ts:99` — asserts the `knowledge_sources` → `/api/v1/knowledge/documents?` alias, direct evidence this drift class already happened once and was patched by hand.",
            "`backend/tests/test_runtime_surface_inventory.py:31-52` — backend route truth is pinned only against itself via per-module route counts and `EXPECTED_ROUTE_INVENTORY_SHA256`, which catches the backend changing but not the frontend failing to follow.",
            "`backend/tests/test_single_page_external_source_sync_api.py:76-82` — the only openapi assertion reads `main_app.openapi()[\"paths\"]` and checks backend-authored paths.",
        ],
        impact=(
            "A route rename or prefix move keeps both suites green while the console 404s, and the "
            "existing alias test is proof this has already happened once."
        ),
        fix=(
            "Add a backend unit-lane contract test (no DB needed) that imports "
            "`main_app.openapi()[\"paths\"]` and asserts every `resource → (path, method)` pair the "
            "dataProvider emits resolves to a real route, driven from a single shared table so the "
            "dataProvider test and the contract test cannot drift."
        ),
    ),
    dict(
        id="TEST-06",
        title="No dependency or security scanning in CI",
        sev="high",
        area="testing",
        labels=["testing", "security", "ops"],
        effort="S",
        problem=(
            "The repository has two workflows, no Dependabot config, and no `pip-audit`, `npm audit`, "
            "CodeQL or SAST step anywhere, so a published CVE in any pinned dependency is invisible "
            "until exploited. The team already patches transitive CVEs by hand via `overrides`, with no "
            "automation to keep doing it."
        ),
        evidence=[
            "Only two workflows exist — `.github/workflows/quality-gates.yml` and `openwiki-update.yml` — and `.github/dependabot.yml` is missing.",
            "No `pip-audit`, `npm audit`, CodeQL or SAST step appears in `.github/workflows/quality-gates.yml`.",
            "Live attack-surface dependencies are pinned in `backend/pyproject.toml` (`pyjwt[crypto]`, `cryptography>=42`, `passlib[argon2]`, `google-genai`, `langchain-openai`) and `frontend/package.json` (`dompurify`, `socket.io-client`, `marked`, `zod`).",
            "`frontend/package.json` carries two `overrides` (`esbuild`, `decode-uri-component`) that are themselves hand-applied transitive-CVE patches — evidence the team cares, with no automation behind it.",
        ],
        impact=(
            "A published CVE in any pinned dependency stays invisible until exploited, on a single "
            "droplet holding candidate PII and Zalo/Facebook provider tokens."
        ),
        fix=(
            "Add `.github/dependabot.yml` for `pip` (backend) and `npm` (frontend), weekly and grouped, "
            "plus an advisory (non-blocking) `pip-audit --strict` and `npm audit --omit=dev` job. Any "
            "advisory that is deliberately accepted gets a comment rather than silence."
        ),
    ),
    dict(
        id="TEST-07",
        title="The vitest claude project matches zero files and is never run",
        sev="high",
        area="testing",
        labels=["testing", "tech-debt"],
        effort="S",
        problem=(
            "`vitest.config.ts` declares a second test project whose include glob matches no file in the "
            "repository, and neither CI nor the Makefile invokes its npm script. It reads as a working "
            "test lane while being dead config that can never pass."
        ),
        evidence=[
            "`frontend/vitest.config.ts:87-90` — project `claude` with `include: [\".claude/**/*.test.mjs\"]` and a 30 s timeout.",
            "A repo-wide glob for `**/*.test.mjs` returns nothing, and `frontend/.claude` does not exist; the only `.claude/` is the repo-root agent config, which contains `hooks/*.cjs`, `skills/` and `agents/` but no tests.",
            "`.github/workflows/quality-gates.yml:138` runs only `npm run test:unit:app`, and `frontend/package.json:9` (`test:unit:claude`) is referenced by neither CI nor the `Makefile`.",
        ],
        impact=(
            "Vitest exits non-zero on \"No test files found\" by default, so anyone running "
            "`npm run test:unit:claude` gets a red result that looks like a broken suite, and any future "
            "hook tests placed at `.claude/**` would silently not run in CI. [INFERRED — the non-zero "
            "exit follows from Vitest's default `passWithNoTests: false`; the script was not executed.]"
        ),
        fix=(
            "Either add `passWithNoTests: true` to the project and wire `npm run test:unit:claude` into "
            "the `frontend-quality` job, or delete the project block and the `test:unit:claude` script "
            "until the hook tests exist. Do not leave a project that can never pass and never runs."
        ),
    ),
    dict(
        id="TEST-08",
        title="Visual-regression baselines are darwin-only and the visual projects are excluded from CI",
        sev="high",
        area="testing",
        labels=["testing", "ops"],
        effort="M",
        problem=(
            "The only pixel-level guard in the repo has four committed baselines, all `-darwin.png`, and "
            "the two visual Playwright projects are excluded from both the chromium and mobile projects "
            "that CI actually runs. The spec was written to be CI-safe — it disables animations and sets "
            "a diff ratio — but it is simply never wired in."
        ),
        evidence=[
            "`frontend/e2e/visual.spec.ts-snapshots/` contains only 4 files, all `*-darwin.png`.",
            "`frontend/playwright.config.ts:74-75` and `:84-85` — the `chromium` and `Mobile Chrome` projects both set `testIgnore: /visual\\.spec\\.ts/`; the visual specs live in the dedicated `visual-desktop`/`visual-mobile` projects at `:98`/`:106`.",
            "`.github/workflows/quality-gates.yml:223` runs `npm run test:e2e:desktop` → `playwright test --project chromium` (`frontend/package.json:10`) and `:225` the mobile equivalent; neither selects a visual project.",
            "`frontend/e2e/visual.spec.ts:87` sets `maxDiffPixelRatio: 0.1` and the documented baseline workflow already exists at `visual.spec.ts:21`.",
        ],
        impact=(
            "The only pixel-level guard for the auth/login shell is never enforced, and even enabling "
            "the projects would fail on ubuntu without `-linux` baselines."
        ),
        fix=(
            "Add a CI job running `npx playwright test --project visual-desktop` and commit ubuntu "
            "baselines generated by `--update-snapshots` on the runner, using the documented workflow at "
            "`visual.spec.ts:21`. If that is not wanted, delete the two visual projects and their "
            "baselines so the repo does not advertise a guard it does not run."
        ),
    ),
    dict(
        id="TEST-09",
        title="Implementation is pinned by inspect.getsource substring assertions",
        sev="medium",
        area="testing",
        labels=["testing"],
        effort="M",
        problem=(
            "Several backend tests read a module's source text and assert that specific tokens appear in "
            "it, which is the inverse of test value: they pass on a refactor that extracts behaviour "
            "into a helper and fail on a pure reformat. They also give false confidence that the "
            "KB-version join is correct without ever executing a query."
        ),
        evidence=[
            "`backend/tests/test_fact_repository.py:17-20` — `assert \"Project.active_kb_version_id == StructuredFact.kb_version_id\" in source`, repeated at `:55-57` and `:68-70`.",
            "`backend/tests/test_outbox.py:416-437` — `assert \"raise RuntimeError\" in src`, `assert \"except Exception\" in src`, `assert \"return None\" in src`; `:363` and `:391` parse the source AST to assert docstring-versus-code structure.",
            "`backend/tests/test_logging_credentials.py:31-32` and `backend/tests/test_outbound_dispatch_worker.py:25-31` — token pins (`silence_credential_bearing_transport_loggers`; `assert \"app.services\" not in source`).",
            "`backend/tests/test_domain_tools.py:182-185` — a forbidden-token scan of `domain_tools` source; this is a legitimate absence guard and is unlike the positive pins above.",
        ],
        impact=(
            "A semantic inversion (`==` → `!=`, or dropping the `IS NULL` legacy fallback) that keeps the "
            "asserted token present would still pass, so these tests stand in for behaviour without "
            "proving it."
        ),
        fix=(
            "Assert behaviour instead: seed a `Project` with `active_kb_version_id = v2` plus one "
            "`StructuredFact` at `v2` and one at `v3`, call `query_active_structured_facts` and assert "
            "exactly the `v2` row returns; call `create_pending_outbox` against a failing session and "
            "assert it raises, then `enqueue_outbox` and assert it returns `None`. "
            "`backend/tests/integration/conftest.py` already provides the disposable DB. Keep the pure "
            "absence guards (`test_domain_tools.py:182`, `test_architecture_boundaries.py`)."
        ),
    ),
    dict(
        id="TEST-10",
        title="~40 assertions test CSS and TSX source text instead of rendered layout",
        sev="medium",
        area="testing",
        labels=["testing", "tech-debt"],
        effort="L",
        problem=(
            "Nine frontend test files import stylesheets or component source via `?raw` and assert "
            "regexes against the text, which passes when a selector is misspelled, shadowed by a later "
            "rule, or applied to an element that is never rendered — exactly the regressions the test "
            "names claim to prevent — and fails on any reformat. The `app` vitest project already runs "
            "in real Chromium, so computed styles are available and cheap."
        ),
        evidence=[
            "`frontend/src/components/atomic-crm/integrations/settings.css.test.ts:3-7` (5 raw imports) plus `:10-100` (12 assertions such as `--settings-control-height:\\s*38px` and `min-height:\\s*44px`).",
            "Eight further files use the same pattern: `conversations/inbox/responsive-visual-regressions.test.ts:3-4`, `kit/tailkit-system.css.test.ts:3`, `projects/projects.css.test.ts:3`, `performance/performance.css.test.ts:3-6`, `personas/persona-layout-regressions.test.ts:3-9`, `users/account-layout-regressions.test.ts:3-8`, `knowledge/knowledge-workspace-layout.test.ts:3-6` and `conversations/inbox/tailkit-redesign.test.ts:3`.",
            "`frontend/src/components/atomic-crm/conversations/ConversationList.test.ts:3` — imports component source via `?raw` rather than rendering the component.",
            "`frontend/vitest.config.ts:47-58` — the `app` project runs in real Chromium, so computed styles and layout rects are measurable in the existing lane.",
        ],
        impact=(
            "`expect(stylesheet).toMatch(/min-height:\\s*44px/)` passes when the rule never applies to a "
            "rendered element, so the touch-target, viewport-overflow and hidden-metadata regressions "
            "the tests are named for are not actually guarded."
        ),
        fix=(
            "Render the component and assert `getComputedStyle(el).minHeight === \"44px\"`, or assert "
            "`el.getBoundingClientRect()` fits the mobile viewport at the mobile breakpoint. Convert the "
            "highest-value cases (touch targets, viewport overflow, hidden metadata) and delete the rest "
            "rather than re-pinning them."
        ),
    ),
    dict(
        id="TEST-11",
        title="Wall-clock timing assertions in the unit lane will flake on a slow runner",
        sev="medium",
        area="testing",
        labels=["testing"],
        effort="M",
        problem=(
            "Several unit tests prove concurrency or deadline behaviour with narrow wall-clock margins, "
            "so a GC pause or scheduler delay on a shared runner makes them red while the code is "
            "correct. The unit lane also has a 20-minute budget and no per-test timeout, so a genuine "
            "hang consumes the whole budget with no signal."
        ),
        evidence=[
            "`backend/tests/test_parallel_tools.py:594-622` — two 50 ms sleeps then `assert elapsed_ms < 90, f\"prefetch was sequential ({elapsed_ms:.0f}ms >= 90ms)\"`; the comment states the intent is to prove `gather()` is used.",
            "`backend/tests/test_turn_deadlines.py:53-56` uses `pytest.approx(1.2, abs=0.05)`, `:64-72` asserts `4.9 < d.remaining(\"unknown_stage\") <= 5.0`, and `:80` uses `pytest.approx(time.time() + 3, abs=0.1)`.",
            "`backend/tests/test_graph_runner_turn.py:1197-1216` — `await asyncio.sleep(0.8)` then `assert zalo.actions.count(\"typing\") >= 1` against a ~0.5 s heartbeat, a 0.3 s margin; `:693` sets `deadline_at_epoch = time.time() + 0.5`.",
            "`backend/tests/test_parallel_tools.py:137` sleeps 0.3 s, and `.github/workflows/quality-gates.yml:20` gives `backend-unit` `timeout-minutes: 20` with no `pytest-timeout` in `backend/pyproject.toml:60-67`.",
        ],
        impact=(
            "A red on a slow runner costs a re-run, and a real hang consumes the entire 20-minute job "
            "budget without identifying the offending test."
        ),
        fix=(
            "Replace wall-clock proofs with the concurrency-counter form the suite already uses "
            "correctly (`test_parallel_tools.py:637-663` asserts `max_active == 1`), or inject a "
            "captured sleep list as `test_graph_decisions.py:317-321` does. Widen the remaining budget "
            "assertions to non-flaking bounds (`abs=0.15`) or freeze the clock, and add `pytest-timeout` "
            "with a per-test cap."
        ),
    ),
    dict(
        id="TEST-12",
        title="The unit lane has no outbound-network guard although the integration lane does",
        sev="medium",
        area="testing",
        labels=["testing"],
        effort="S",
        problem=(
            "The integration conftest blocks all non-loopback HTTP and socket connects, but the unit "
            "conftest has no equivalent guard, and it explicitly clears the shared httpx client "
            "registry before and after every test. Existing tests stub at the client seam, so nothing "
            "fails if a new test forgets to."
        ),
        evidence=[
            "`backend/tests/integration/conftest.py:239-263` — `_block_external_http` monkeypatches `httpx.AsyncClient.request`, `socket.socket.connect` and `socket.connect_ex` to raise on any non-loopback host.",
            "`backend/tests/conftest.py` (~55 lines) provides only `_isolate_redis` and `_reset_http_singleton_registry` — no network guard.",
            "`_reset_http_singleton_registry` clears `app.core.http._CLIENTS` before and after every test, which makes construction of a real client more likely in the unit lane.",
            "Current stubbing is at the client seam only — `backend/tests/test_zalo_oa_service.py` captures URLs, `test_graph_decisions.py` installs a fake httpx client, `test_llm_probe.py` patches `post` — so an unstubbed call has nothing to stop it.",
        ],
        impact=(
            "An unstubbed call silently makes a live request — cost, latency, nondeterminism, and in CI "
            "possibly a hang until the 20-minute job budget fires."
        ),
        fix=(
            "Port `_block_external_http` into `backend/tests/conftest.py` as an autouse fixture allowing "
            "`127.0.0.1`, `localhost` and `testserver`, so any unstubbed outbound call fails loudly and "
            "immediately with the offending host in the message."
        ),
        notes=(
            "Do not ticket the auth suite — it is genuinely well tested: `backend/tests/test_security.py` "
            "covers argon2 per-call salting and tampered/malformed/expired JWT → `ValueError`, and "
            "`test_identity_authentication.py` asserts validation order (non-access token and invalid "
            "UUID rejected before any DB lookup) and the exact 401 body."
        ),
    ),
    dict(
        id="TEST-13",
        title="56 migrations, ~8 with roundtrip coverage, and none of those run in CI",
        sev="medium",
        area="testing",
        labels=["testing", "ops"],
        effort="L",
        problem=(
            "The Alembic history holds 56 revisions, of which only about eight have any forward/backward "
            "roundtrip test, and none of those eight are reachable in CI. Because the blue/green flow "
            "runs `alembic upgrade head` against production and one Makefile target explicitly accepts "
            "downtime for non-additive migrations, a wrong `downgrade()` is discovered during a rollback."
        ),
        evidence=[
            "`backend/alembic/versions/` holds 56 files (`0001_baseline` … `0054_channel_account_projects`, plus `091e7edc9f76_merge_*`).",
            "Roundtrip/downgrade coverage exists for 0042 (`backend/tests/integration/test_installation_migration_roundtrip.py:37-105`), 0045 (`test_runtime_authority_stamp_migration.py:39-148`), 0047 (`test_canonical_channel_identity_migration.py:117-420`), 0049 (`test_adapter_persona_assignment_migration.py:35-98`), 0050 (`test_data_ingestion_recovery_migration.py:49`), 0051 (`test_bot_run_decision_trace_migration.py:21`), 0052 (`test_single_page_external_source_sync_migration.py:36`) and project-knowledge (`test_project_knowledge_migration.py:39-66`).",
            "No forward/backward test exists for 0041, 0043, 0044, 0046, 0048, 0053, 0054, nor for any of 0001–0040.",
            "All eight are unreachable in CI per TEST-01, while `backend/Makefile:155` (`deploy-breaking`) accepts downtime specifically for non-additive migrations.",
            "Where the tests do exist they are strong: `test_canonical_channel_identity_migration.py:402` proves downgrade fails closed when Messenger rows exist, and `test_project_knowledge_migration.py:39` seeds pre-0047 data before upgrading.",
        ],
        impact=(
            "A broken `downgrade()` is only discovered during a production rollback — the worst possible "
            "moment — and the deploy flow upgrades to head on every release."
        ),
        fix=(
            "Add one parametrized test that walks every revision: `upgrade <rev>` → `downgrade -1` → "
            "`upgrade head`, asserting `alembic heads` is singular and the expected tables and columns "
            "exist at each step, and asserting that `downgrade` raises for intentionally irreversible "
            "migrations rather than silently no-op'ing. It is a single file reusing `integration_database`."
        ),
    ),
    dict(
        id="TEST-14",
        title="E2E is a 2-test smoke and the highest-blast-radius journeys are mock-only",
        sev="medium",
        area="testing",
        labels=["testing"],
        effort="M",
        problem=(
            "The browser suite is exactly two tests — login plus dashboard render, and conversation "
            "takeover/release. Nothing exercises knowledge upload through ingestion to a terminal "
            "status, persona/adapter assignment, or the bot-run decision-trace UI against the real "
            "backend, even though the harness already blocks external network, resets the DB per test "
            "and can drive those journeys."
        ),
        evidence=[
            "`frontend/e2e/vfic.spec.ts:3-55` — exactly two tests: login and dashboard render, and conversation takeover/release.",
            "`frontend/e2e/fixtures.ts:74-97` — external network is blocked and asserted empty at `:88-95`, and the DB is reset per test at `:44-53`, so the harness is already capable of driving real journeys.",
            "`frontend/playwright.config.ts:37` sets `retries: process.env.CI ? 2 : 0`, so a flaky added spec would burn three times its duration in the closest-to-limit job.",
            "Backend fixtures for both missing journeys already exist: `e2e_harness.py` seeds, and `backend/tests/integration/test_bot_run_decision_trace_migration.py` covers the trace data shape.",
        ],
        impact=(
            "The journeys with the largest user-visible blast radius (\"I uploaded a document and nothing "
            "happened\", \"the trace panel shows nothing\") are covered only by mocked unit tests, so a "
            "frontend↔backend integration break passes."
        ),
        fix=(
            "Add two e2e specs: upload a knowledge document and assert it reaches a terminal status in "
            "the list, and open a conversation's bot-run trace and assert a run row plus its "
            "decision-trace detail renders. Both have backend fixtures already."
        ),
    ),
    dict(
        id="TEST-15",
        title="Sleep-pumped synchronization, deploy-Makefile test fakes, and AST-structure pins",
        sev="low",
        area="testing",
        labels=["testing", "tech-debt"],
        effort="S",
        problem=(
            "Three low-severity patterns remain in the suite: `await asyncio.sleep(0)` used as a "
            "synchronization primitive for fire-and-forget tasks, deploy-Makefile tests that re-implement "
            "the `bash`/`curl`/`docker` toolchain as fakes that accept essentially any invocation, and "
            "AST-structure pins that constrain code shape rather than behaviour."
        ),
        evidence=[
            "`backend/tests/test_concurrency.py:425-426` — two `await asyncio.sleep(0)` calls used to pump a fire-and-forget task before the assertion; the same pattern appears at `test_direct_turns.py:29-30`, `test_main_lifespan_cleanup.py:88`, `test_worker_async_runner.py:76,101,165` and `test_performance_endpoint.py:620`.",
            "`backend/tests/test_deployment_makefile.py:351-500` — `textwrap.dedent` fakes for `bash`, `curl` and `docker`; `:452-495` returns `raise SystemExit(0)` for essentially every docker invocation, so the test can detect only that some command ran, not that its shape is right.",
            "`backend/tests/test_webhooks.py:1060-1063` — parses `ZaloWebhookService.handle`'s source and walks it with parent tracking to assert \"structural dominance\"; `:1154-1157` strips docstrings via AST and scans the remaining code for provider names.",
        ],
        impact=(
            "The sleep-pumped assertions pass only because the event loop happens to schedule the task "
            "after N yields, so adding one `await` before its first real suspension fails the test for a "
            "reason unrelated to the invariant; the deploy fakes must be edited whenever `bg_deploy.sh` "
            "changes its tool usage; and the AST pins fail on a semantically equivalent early-return "
            "refactor."
        ),
        fix=(
            "Await the actual task handle or poll the module's task set explicitly — "
            "`test_concurrency.py:435` already asserts `events_mod._background_tasks == set()`, so use "
            "that as the wait condition. Keep the deploy ordering assertions (healthcheck → smoke → "
            "flip, abort-before-flip) and drop the parts that model tool behaviour, adding `shellcheck` "
            "on the scripts instead. Keep the provider-name leak scan at `test_webhooks.py:1154-1157` "
            "and replace the dominance pin with a behavioural assertion."
        ),
    ),
]
