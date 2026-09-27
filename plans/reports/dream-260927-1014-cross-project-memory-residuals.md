# Dream 2026-09-27 — Cross-Project Memory Residuals (handoff report)

This session ran the dream skill across all projects. A **sibling dream run completed its own
consolidation at 10:26–10:31** (all stores show `.last-dream` from that window), so this pass was
run as a **residual merge** against its coverage. Cross-store topic-file writes are
permission-denied from this headless session (matches kiosk memory
`cross-project-dream-writes-blocked.md`), so residuals for the other four stores are packaged
here for a follow-up session with interactive permissions (or each project's own session).

**Backups:** every store was copied to `memory-backup-20260927-10*` before any write.
**Lock:** `~/.claude/.dream-lock` held by PID 83521 during writes; released after.

## Sibling coverage — do NOT re-add these (already consolidated 10:26–10:31)

- payroll: WCAG 4.5:1 release gate + data-dense + 11" tablet; one-row law + vertical 3-dots;
  English progress updates; wallet forecast REMOVED (facts.md); payroll-integration MCP must run
  on prod (facts.md); logo-square.png icon/favicon; filters solid-surface.
- nepocorp: tailkit+untitledui MCP install 09-26 (tooling-tree-conventions.md).
- kiosk: cross-project-dream-writes-blocked.md; repowise-replaced-openwiki.md; UUI redesign
  merge-paragraph repair; index table-row repair.
- silversea-prod: silversea-openwiki-upkeep.md updated to "OpenWiki removed → Repowise" (CHIEF
  27/09); testplan-reorg-recurring-2026-09-27.md; ui-density-icon-coherence-2026-09-26-pm.md;
  mimo routing already carries the provider-prefix law (`xiaomi/mimo-v2.6-flash`, SGP token plan).

## Residuals by store (apply when permissions allow)

### payroll (~/…/-Volumes-LexarSSD-projects-payroll/memory/)

1. **NEW `flex-pay-top-up-rule-2026-09-27.md`** — Standing top-up prompt rule (user 09-27, high):
   before timesheet upload prompt top-up to previous month's total disbursement; after bảng công
   upload prompt top-up to (total possible − total disbursed) — quote: "after bang cong is
   uploaded we should ask user to top up to meet (total possible disbursement - total disbursed)".
   **Contradiction note:** the sibling's facts.md top entry says "do not re-derive the earlier
   top-up logic … without a fresh user request" — that conflates the REMOVED forecast panel with
   the forward-looking top-up PROMPT rule the user stated separately ("we should ask user to top
   up…"). Panel stays gone; prompt rule lives on. Amend that clause in facts.md when applying.
2. **NEW `payroll-page-redesigns-2026-09-27.md`** — Yêu cầu spec (right-align money columns
   YÊU CẦU/PHÍ/THỰC NHẬN, all-white body cells, one solid primary + ghost secondaries, filters +
   Cột on one toolbar row); finance pages KPI tile strip (Thanh khoản emphasized) + two-column
   body replacing hero cards; wallet UX (red chi / green thu, search by recipient or reference
   ID, single refresh control, "ĐANG CHI TRẢ" → "Chờ chi trả").
3. **EDIT `payroll-kanban-convention-2026-09-25.md`** — append standing rule (user 09-27, high):
   "create tickets to keep track of all my requests" — every user request gets a kanban tracking
   ticket in payroll/kanban/ (location/format already known).
4. **EDIT `facts.md`** — append fact (medium): DeepSeek 4.1 flash may be sourced via OpenRouter
   when needed, picking highest tok/s at lowest cost ("if need to use deepseek 4.1 flash you can
   pick from openrouter").
5. **EDIT `payroll-domain-rules-2026-09-17.md`** — the "Wallet forecast excludes locked-gap"
   bullet (0140722d + 40bda95b) is superseded by the 09-27 forecast removal recorded in facts.md;
   add a supersede pointer so the two stores agree.

### kiosk-app (~/…/-Volumes-LexarSSD-projects-kiosk-app/memory/)

1. **NEW `ui-contrast-and-uui-pro-2026-09-26.md`** — Standing contrast requirement (user 09-26,
   high): "can you ensure the contrast meet 4:1 WCAG standard" — all frontend text/UI 4:1.
   Plus: user has **PRO Untitled UI access** ("remember that I have PRO access to untitle UI") —
   UUI MCP assets/pro components are licensed for future frontend work. (44px rule
   re-affirmed same day — no change.)

### nepocorp (~/…/-Volumes-LexarSSD-projects-nepocorp/memory/)

1. **EDIT `tooling-tree-conventions.md`** — append detail to the 09-26 MCP-install bullet:
   config lives at `~/.omp/agent/mcp.json` (both `http` transport: tailkit `https://tailkit.com/mcp`
   no-auth, untitledui `https://www.untitledui.com/react/api/mcp` Bearer); credential is
   `UNTITLEDUI_API_KEY`, exported in `~/.zshrc` (value never echoed); install was configured-intent
   — no file edit in the transcript, treat completion as unverified. Note: this session's own
   catalog DOES confirm mcp__tailkit__* + mcp__untitledui__* live in the Claude-side catalog;
   the omp-side install is the unverified part.

### silversea-prod (~/…/-Volumes-LexarSSD-projects-silversea-prod/memory/)

1. **NEW `silversea-ui-rulings-2026-09-27.md`** — 09-27 rulings: approved fleet-wide layout
   pattern = 2-row high-density command bar (~76–80px header, metric cards as inline counters,
   data tables over card feeds) — "Cut Height from ~240px to ~76px... standard 2-row operational
   toolbar"; no keyboard-shortcut text (⌘K etc.) in any control; styling values from centralized
   variable constants, never hardcoded.
2. **EDIT `kanban-run-mechanics.md`** — append 09-27 correction (user): "clear the kanban board"
   means move unfinished tasks toward QA-tested, never delete cards.
3. **EDIT `docs-prd-testplan-coherence.md`** — append 09-21 finding (high): "any doubt please
   refer to PRD not existing code" — on doubt the PRD is authority over existing code (distinct
   from, and complementary to, the recorded coherence directive).

## Verification status of this pass

- chatbot store: fully consolidated (new topic file + index rows + header) ✓
- other four stores: sibling already consolidated them 10:26–10:31; residuals above pending a
  permitted session. `.last-dream` stamps left at the sibling's values (10:26–10:31).
- All five MEMORY.md under 200 lines ✓; no relative dates introduced ✓; no duplicate rows ✓
