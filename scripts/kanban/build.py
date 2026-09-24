"""Render the tech-debt audit backlog into the kanban board.

Board layout follows the house kanban convention (see the `kanban-work` practice):

    kanban/
      TODO/            waiting
      IN_PROGRESS/     claimed, being implemented
      DEV_COMPLETED/   local criteria evidenced
      QA_TESTED/       verified locally end to end

`kanban/` is exactly those four column folders — no index, no sidecars. This
generator and its data modules live OUTSIDE the board, under `scripts/kanban/`.

Cards are markdown, named `YYYYMMDD_<ID>-<slug>.md` (date prefix + the stable
ticket id + a kebab-case slug). The id is kept in the filename because the cards
cross-reference each other by id.

Run:  python3 scripts/kanban/build.py
Idempotent: rewrites every card from the data modules, so the data is the source
of truth for content and column. A card's true column is whatever the data says;
move a card by editing its `column` in the data module, not by hand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
KANBAN = REPO_ROOT / "kanban"

sys.path.insert(0, str(HERE))

import tickets_a  # noqa: E402
import tickets_b  # noqa: E402
import tickets_c  # noqa: E402
import tickets_d  # noqa: E402

TICKET_DATE = "20260924"
COLUMNS = ["TODO", "IN_PROGRESS", "DEV_COMPLETED", "QA_TESTED"]
COLUMN_STATUS = {
    "TODO": "todo",
    "IN_PROGRESS": "doing",
    "DEV_COMPLETED": "dev-completed",
    "QA_TESTED": "qa-tested",
}

# Landed work. Keys are ticket ids; values set the card's column and append an
# evidence log to the card. This lives here rather than in the card files so a
# regeneration cannot discard it, and rather than in the ticket data modules so
# the audit data stays a record of the audit rather than of the remediation.
COMPLETIONS: dict[str, dict] = {
    "FE-01": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "decb8b63 — `ZaloIntegrationPage.tsx` 2072 → 98 LOC: descriptor table to `domain/providerDescriptors.ts`, state owners to `application/{useSettingsBundle,useZaloForm,useProviderPanels}.ts`, chrome/sections to `presentation/*`; the three save/dirty mechanisms collapse onto one.",
            "Deliberate deviation: the settings navigation is unchanged. The embedded `PersonaList`, `UserList` and `FacebookMessengerIntegrationPage` render from thin section components instead of moving to their own routes, because that would be a user-visible navigation change.",
            "Verified: `npx vitest --run src/components/atomic-crm/integrations` — 5 files / 48 tests pass; `npm run typecheck` clean.",
        ],
    },
    "FE-02": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "0567d63b — `ProjectKnowledgePanel.tsx` 1095 → 316 LOC, 21 `useState` → 2; data layer to `projects/application/*` (catalog + cutover poll, category/single-page/discovery drafts), rendering to `projects/presentation/*`.",
            "One write path: the `project-knowledge-service` facade. `DiscoveryCardEditor`'s react-admin write became the port operation `updateProjectDiscoveryCard` (`PATCH /api/v1/knowledge/projects/{id}`, matching the backend `ProjectUpdate` schema). The two surviving `useRefresh()` calls are cache invalidation for the react-admin-cached project record, not a second write path.",
            "The `exhaustive-deps` disable and both hand-rolled generation guards are gone.",
            "Verified: `ProjectKnowledgePanel.test.tsx` 13/13 (harness-only change), `projects` suite 66 tests pass; a canary that broke one Vietnamese string flipped exactly the dependent test.",
        ],
    },
    "FE-03": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "131f8c67 — LRU bound of 5 conversations enforced through the existing `clear(convId)`, which is now its only removal mechanism; the active conversation is excluded from its own eviction pass so in-flight optimistic messages survive.",
            "The port's unselected `subscribe` became `subscribeTo(selector, listener)` over `subscribeWithSelector`; a write to one conversation no longer wakes subscribers of another.",
            "Deleted the three dead exports (`useConversationMessages`, `useConversationFlags`, `getNewestRealMessageId`).",
            "Verified: 16 tests in `useConversationRealtime.test.ts` cover the bound, the optimistic-survival guarantee and the fan-out isolation.",
        ],
    },
    "FE-04": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "1535255c — four pollers collapsed into one `useAttentionCounts()` returning `{total, byProvider}` under a single key family; inbox polling drops from 8 requests/min to 4 and the cadence moves to 60s.",
            "Per-provider fetches were kept deliberately: the backend returns only `{\"count\": n}` per provider filter and has no breakdown endpoint, and `contact_channel_identities.provider` is an unconstrained string column, so a derived total could undercount the bell.",
            "Socket-driven invalidation was evaluated and rejected: `message.created` is routed only to the `conv:<id>` room a client joins by opening that conversation.",
            "Verified: topbar + `ChannelAdapterSelector` tests pass (8 tests) under the new contract.",
        ],
    },
    "FE-05": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "ff2fbfc3 — rows keep the raw `conversations` array for identity; `presentation`/`snippet` resolve through a per-id view-model cache (`conversation-row-view-model.ts`) that reuses the previous object while inputs are unchanged. The row takes its own `isRead` boolean instead of the shared `Set`, and `onSelect` is stabilised via a ref.",
            "Verified by falsifiable render tests: a search keystroke and a read-toggle each leave sibling rows un-rendered, each with a positive control. Both tests fail if the view-model reuse or the stable `onSelect` is reverted.",
        ],
    },
    "FE-06": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "5751a766 — deleted `kit/{stat-card,data-table-card,sidebar}.tsx`, the `AlternateCard` export and their four test files; kept `PageShell`/`PageHeading`/`EmptyState` and the `tailkit-system.css` token bridge.",
            "Removed 12 unreferenced catalog blocks from `vietnameseCrmMessages.ts`; every deleted key grep-verified to have zero references, all eight live resources kept.",
            "Removed the three dangling `registry.json` entries so no manifest path points at a deleted file.",
            "Verified: kit/users/commons suites 7 files / 23 tests pass.",
        ],
    },
    "FE-07": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "7f28d2a8 — 91 catalog keys added (235 → 326), 26 components migrated onto `useTranslate`, one ellipsis form used consistently, and the `ra.saved_queries.*`/adjacent `ra.*` gaps filled so no English leaks into the Vietnamese UI.",
            "`leads/domain/candidateProfile.ts` moved from `label: string` to `labelKey: string`, so one field definition feeds both the candidate dialog and the conversation context panel.",
            "Verified: the component tests assert Vietnamese output, so their passing is the evidence wording survived; full suite 595 tests green.",
        ],
    },
    "FE-08": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "f81c1042 — `no-explicit-any` scope made recursive and extended to `src/components/atomic-crm/**` (previously unguarded, 62k LOC); the product tree lands with zero new violations.",
            "The 31 vendored `admin/` files keep their explicit file-level disables by decision — they are a copy-paste dependency and rewriting their type signatures is not worth the regression risk.",
            "The two `as unknown as` casts at the conversation-mutation seam are replaced by one real `CrmDataProvider` type, so dropping a provider method is now a compile error.",
            "Verified: `npm run lint` 0 errors, `npm run typecheck` clean, provider/chat tests 28 pass.",
        ],
    },
    "FE-09": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "Landed in 7f28d2a8 (swept in by a directory pathspec alongside FE-07 and FE-12 — attribution recorded here).",
            "`ExternalSourceList.tsx` 568 → 286 lines: the 466-poll state machine is now `useQuery({refetchInterval: (q) => nextPollDelay(q.state.data, watch, Date.now())})` with `refetchIntervalInBackground: false`; 15 state holders → 7.",
            "The follow-up policy moved to `projects/domain/externalSourcePolling.ts` (pure, with 5 boundary tests) and row rendering to `projects/presentation/ExternalSourceRow.tsx`.",
            "Verified: `externalSourcePolling.test.ts` covers the 4s/30s boundary and budget expiry; a new test proves a hidden tab stops polling and resumes.",
        ],
    },
    "FE-10": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "8be895b6 — the module-scope `createLeadRealtimePort(getRealtimeSocket())` became a lazy, socket-memoized getter, so socket.io-client is no longer constructed at import and its chunk is not fetched on first paint.",
            "`apiClient` gained an `onAccessTokenRotated` seam and the socket re-handshakes on it, so a long-lived connection re-presents a rotated JWT instead of silently going dead.",
            "Fixed a pre-existing bug found on the way: `leadRealtime` did not re-emit `join lead` on reconnect, so `lead.updated` silently stopped after any network blip. It now rejoins through one shared `join()` helper.",
            "Verified by mutation: re-adding the module-scope construction fails the suite at import with a thrown sentinel; the re-auth test reproduces the real library's auth-callback contract.",
        ],
    },
    "FE-11": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "21221d2c — the last `GroupedVirtuoso` migrated to `virtua` (desktop `VList`, mobile `WindowVirtualizer` since the workspace frame is not a scroll container at ≤767px), with the day grouping flattened into one virtualized child list so headings stay virtualized with their rows.",
            "`manualChunks` now names `virtua` and `zod` instead of the legacy library. Verified in the build output: `virtua-vendor` and `zod-vendor` exist, `virtuoso-vendor` is gone, and react-virtuoso appears in no chunk.",
            "`react-virtuoso` removed from `package.json` in 3ca1ee78 once nothing imported it.",
            "Verified: the render test now exercises the real virtualizer instead of mocking react-virtuoso, and asserts the day-group heading still renders.",
        ],
    },
    "FE-12": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "Landed in 7f28d2a8 (swept in by a directory pathspec alongside FE-07 and FE-09 — attribution recorded here).",
            "`gcTime` dropped from 24h to the TanStack default 5 minutes (nothing persists across reloads, so the 24h window only grew in-tab memory), and mutations moved from `offlineFirst` to `online` so a write reported as failed cannot land later.",
            "Queries keep `offlineFirst`, and the deliberate `staleTime 25s < refetchInterval 30s` pairing in the dashboard is untouched.",
            "Verified by a regression test written red-first: restoring the old config makes it fail at `expect(mutation.state.isPaused).toBe(true)` and the retention assertion.",
        ],
    },
    "FE-13": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "31f78da5 — both slice-migration shims finished and deleted: `conversation-list-filters.ts` (which also carried the live `getChannelProviderSearchParams`, moved into `domain/`) and the `messageOrdering` re-export; 5 importers repointed.",
            "Three feature tests moved beside their subjects and renamed to the kebab-case convention; `candidateNotes.ts` moved to `domain/candidate-notes.ts` so its test had a subject to sit beside (2 importers repointed).",
            "The layering rule is now recorded in `frontend/AGENTS.md`. Deliberately not applied to `integrations/`/`dashboard/` here — the god files were split along these seams and `dashboard/` stays flat.",
            "01000395 keeps `registry.json` in step with the moved modules.",
            "Verified: conversations suite 21 files / 121 tests pass.",
        ],
    },
    "FE-14": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "decb8b63 — one `SecretField` + `PlainField` pair over a shared `FieldShell` replaces `CredentialSecretField` and the inline `MetaAppSecretField`/`MetaAppPlainField`. The two pages' real differences became props: supplying `notify` adds the copy action (Zalo), supplying `reveal` makes the eye fetch the stored secret and render read-only while revealed (Facebook).",
            "The Zalo page's load/save/test moved onto TanStack Query with the same key conventions the Facebook page already used. `FacebookMessengerIntegrationPage` 794 → 676 LOC.",
            "Verified: `CredentialSecretField.test.tsx` moved to `presentation/SecretField.test.tsx` with assertions preserved and extended; integrations suite 48 tests pass.",
        ],
    },
    "FE-15": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "21221d2c — `filterHumanInterventions`, `groupCandidatesByDay` and the reduce-count are memoized on their real inputs, and `saveCandidateProfile` no longer refetches on the failure path (a failed edit used to double list traffic).",
            "Verified: dashboard suite 5 files / 59 tests pass.",
        ],
    },
    "FE-16": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "e0ea8c8b — the unreachable English `lib/i18nProvider.ts` deleted; `i18nProvider` is now a required prop on `Admin`/`CRM`, which also removes the upward `admin/` → `atomic-crm/` import the first fix would have needed and keeps the enforced `atomic-crm → admin → ui` direction.",
            "3ca1ee78 — six unused dependencies removed (each grep-verified at zero importers): `react-virtuoso`, both `@tanstack` persister packages, `diacritic`, `qs`, `ra-language-english`. The vestigial `pnpm-lock.yaml` is deleted too — the repo is npm (`npm ci` in CI and the Dockerfile) and the second lockfile was already pinning `react-virtuoso` at a different version.",
            "The CSS-scoping third of this card is split out as FE-19 and deliberately deferred: it needs browser QA per screen and the audit advised against a big-bang rewrite.",
            "Verified: `npm run build` succeeds (2.55s) and the full unit suite passes after the removals.",
        ],
    },
    "FE-18": {
        "column": "DEV_COMPLETED",
        "evidence": [
            "8d8740d1 — `npm run lint` glob quoted (also on `lint:apply`). It previously lints 11 top-level files and never reached `src/components/**`, so the script exited 0 regardless of the code and the CI Lint step enforced nothing. It now lints 457 files with 0 errors.",
            "The gate is proven real, not assumed: the newly-live rule immediately caught a genuine `react-hooks/rules-of-hooks` violation (a conditional `useTranslate` introduced during FE-07), which was fixed.",
        ],
    },
}

SEV_ORDER = ["critical", "high", "medium", "low"]
SEV_LABEL = {
    "critical": "P0",
    "high": "P1",
    "medium": "P2",
    "low": "P3",
}
AREA_TITLE = {
    "security": "Security",
    "reliability": "Reliability",
    "performance": "Performance",
    "architecture": "Architecture & dead code",
    "frontend": "Frontend",
    "testing": "Testing & CI",
    "ops": "Ops, deploy & data",
    "docs": "Docs & repo hygiene",
}


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:64].rstrip("-")


def _existing_column(ticket_id: str) -> str | None:
    """Read the column a card currently occupies on disk.

    Progress state is mutable and is advanced by moving the card file; the audit
    data only records where a card *started*. A rebuild must never drag a card
    backwards, so the on-disk column wins unless the ticket data (or the
    COMPLETIONS table below) declares one explicitly.
    """
    for col in COLUMNS:
        if (KANBAN / col / f"{TICKET_DATE}_{ticket_id}-").parent.exists():
            for path in (KANBAN / col).glob(f"{TICKET_DATE}_{ticket_id}-*.md"):
                text = path.read_text(encoding="utf-8")
                m = re.search(r"^column: (\w+)$", text, re.MULTILINE)
                if m and m.group(1) in COLUMNS:
                    return m.group(1)
    return None


def tickets():
    out = []
    for mod in (tickets_a, tickets_b, tickets_c, tickets_d):
        out.extend(mod.TICKETS)
    seen = set()
    for t in out:
        assert t["id"] not in seen, f"duplicate id {t['id']}"
        seen.add(t["id"])
        done = COMPLETIONS.get(t["id"])
        if done:
            t["column"] = done["column"]
            t["evidence_log"] = done["evidence"]
        col = t.get("column")
        assert col is None or col in COLUMNS, f"{t['id']}: bad column {col}"
    out.sort(key=lambda t: (SEV_ORDER.index(t["sev"]), t["id"]))
    return out


def card_name(t) -> str:
    return f"{TICKET_DATE}_{t['id']}-{slugify(t['title'])}.md"


def render_card(t, column: str) -> str:
    lines = [
        "---",
        f"id: {t['id']}",
        f"title: {json.dumps(t['title'], ensure_ascii=False)}",
        f"severity: {t['sev']}",
        f"area: {t['area']}",
        f"labels: [{', '.join(t['labels'])}]",
        f"effort: {t['effort']}",
        f"status: {COLUMN_STATUS[column]}",
        f"column: {column}",
        f"opened: {TICKET_DATE[:4]}-{TICKET_DATE[4:6]}-{TICKET_DATE[6:]}",
        "---",
        "",
        f"# {t['id']} — {t['title']}",
        "",
        f"**Severity:** {t['sev']} · **Area:** {t['area']} · **Effort:** {t['effort']} · "
        f"**Labels:** {', '.join(t['labels'])}",
        "",
        f"**Trạng thái:** {column}",
        "",
        "## Problem",
        "",
        t["problem"],
        "",
        "## Evidence",
        "",
    ]
    lines += [f"- {e}" for e in t["evidence"]]
    lines += ["", "## Impact", "", t["impact"], "", "## Suggested fix", "", t["fix"], ""]
    if t.get("notes"):
        lines += ["## Notes", "", t["notes"], ""]
    if t.get("evidence_log"):
        lines += ["## Evidence log", ""] + [f"- {e}" for e in t["evidence_log"]] + [""]
    lines += [
        "---",
        "",
        f"_Opened {TICKET_DATE[:4]}-{TICKET_DATE[4:6]}-{TICKET_DATE[6:]} from the read-only "
        "tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is "
        "grounded in the cited `path:line` locations._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ts = tickets()

    for col in COLUMNS:
        (KANBAN / col).mkdir(parents=True, exist_ok=True)

    placed: dict[str, list] = {c: [] for c in COLUMNS}
    for t in ts:
        column = t.get("column") or _existing_column(t["id"]) or "TODO"
        placed[column].append((t, card_name(t)))

    # Regeneration is authoritative for *content* but must not resurrect a card
    # that has been deleted on purpose, so clear the columns first.
    for col in COLUMNS:
        for stale in (KANBAN / col).glob("*.md"):
            stale.unlink()

    for col, items in placed.items():
        for t, name in items:
            (KANBAN / col / name).write_text(render_card(t, col), encoding="utf-8")

    print(f"wrote {len(ts)} cards into {KANBAN}")
    for col in COLUMNS:
        print(f"  {col}: {len(placed[col])}")

    total = len(ts)
    by_sev = {s: sum(1 for t in ts if t["sev"] == s) for s in SEV_ORDER}
    done = len(placed["DEV_COMPLETED"]) + len(placed["QA_TESTED"])
    print(
        "  severity: "
        + " · ".join(f"{SEV_LABEL[s]} {by_sev[s]}" for s in SEV_ORDER)
        + f" · closed {done}/{total}"
    )


if __name__ == "__main__":
    main()
