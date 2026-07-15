---
date: 2026-07-15
session: conversation-scroll-affordance
---

# Journal: 2026-07-15 — Conversation viewport and scroll affordance

## Context

Recruiters reported a "page is clipped" / "composer below the fold" impression
in the inbox conversation view, especially for `bot`-owned and `closed`
conversations. The scout confirmed the desktop height chain was already
structurally bounded (`100dvh` shell → `minmax(0,1fr)` grid → `virtua` scroller
→ in-flow footer). The defect was state-driven, not geometric: bot mode
suppressed the footer entirely (`showComposerTakeoverNotice={false}`), closed
mode showed a vague disabled composer (`Chưa sẵn sàng`), and the transcript
scrollbar was hidden. The result read as an unbounded transcript even though the
layout was technically correct.

## What Happened

- **Persistent mode-aware footer.** `ChatThread` now always renders the bottom
  row for a selected conversation. `human`/`semi_auto` → composer; `bot` →
  existing takeover explanation + the existing mode-gated `Tiếp quản`; `closed`
  → a read-only `.closed-note` explanation with no invented send/reopen action.
  Backend ownership enforcement is unchanged.
- **Split a conflation.** The single `hasNewerMessages` boolean was doing two
  jobs. Split into `isAwayFromBottom` (viewport position — drives whether the
  latest control is visible) and `hasUnseenLatest` (author/type-aware arrival —
  drives whether it escalates to the strong `Tin nhắn mới` pill). Only threshold
  crossings update React state; raw scroll distance stays in refs.
- **Author/type-aware unseen contract.** Added `isUnseenWorthyArrival()`: own
  optimistic send, its server echo, system events, and history prepends never
  qualify; candidate inbound, bot replies, and *other* recruiters' replies do.
  A local send explicitly returns the sender to latest.
- **Reduced-motion-aware jump + focus map.** `handleJumpToNewest` now selects
  `auto` vs `smooth` from a reactive `matchMedia` listener and moves focus to a
  mode-appropriate stable target (textarea / takeover button / closed status)
  *before* the button unmounts, so keyboard users never lose their place.
- **Desktop scroll indicator + mobile safe area.** Replaced the always-hidden
  scrollbar with a thin transparent-track scrollbar using existing semantic
  tokens (coarse pointers keep it hidden). Both latest-control variants meet the
  44px touch target; footer padding accounts for `env(safe-area-inset-bottom)`.
- **Focused browser-component tests.** 16 new tests: four-mode footer rendering,
  latest-control visibility, and a pure unit suite locking the unseen-content
  contract in CI.

## Reflection

The key insight was that the "broken" feeling came from overloading one boolean
with two meanings and from suppressing the bottom chrome in two modes — not from
a layout bug. Once the footer is always present and position-state is separated
from unseen-arrival state, the existing grid reads as an intentional bounded
workspace in every mode. The author/type discriminator matters: labelling your
own just-sent message as "Tin nhắn mới" would be actively confusing.

The scoped-change discipline paid off again. By refusing to touch the store,
realtime, ordering, global tokens, or the virtualization architecture, the
change stayed presentation-only and rollback needs no data/API action. The
pre-existing dead `composerReserve`/spacer path and the fragile direct-show
route were deliberately left untouched — narrowing scope is cheaper than
expanding it under deadline.

## Decisions Made

- Keep the three-row grid; do not overlay or `position: fixed` the footer.
- `closed` mode is explanatory only — no reopen action unless backend
  authorization exists. UI must not imply permission it cannot grant.
- Mock `virtua`'s `VList` as a plain scroll container in tests. Its internal
  React-dispatcher assumptions don't hold under `vitest-browser-react`; the
  acceptance criteria are about ChatThread's own footer/latest logic, not
  virtualization. The real scroll architecture is covered by typecheck + the
  isolated synthetic QA in phase-03.
- Export `isUnseenWorthyArrival` so the contract is unit-testable in CI.

## Follow-ups (not in this change)

- Phase-03 manual viewport matrix (1440×720 / 390×844 paired screenshots with
  synthetic data) remains an operator step — it requires a running dev stack and
  ephemeral capture outside the repo.
- The dead `--chat-composer-reserve` / `.chat-history-bottom-spacer` measurement
  path is pre-existing cleanup, scoped out here.
- `prefers-reduced-motion` reactivity added; a future hardening pass could add
  a `matchMedia` listener for the mobile keyboard / `100dvh` interaction.
