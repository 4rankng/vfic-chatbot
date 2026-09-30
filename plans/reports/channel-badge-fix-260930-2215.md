# Channel badge fix — per-account OA badges in the TingHire inbox

Date: 2026-09-30 · Agent: channel-badge-fix · Territory: `frontend/src/components/atomic-crm/conversations/**` + `frontend/src/components/atomic-crm/types.ts` (nothing else touched)

## Defect

OA account rows were indistinguishable. The row chip and detail header derived
their label from `channel_identity.provider` alone, so both the Viet Phap OA
(`account_key="default:zalo_oa"`) and the TingTing OA
(`account_key="tingting"`, backend constant `TINGTING_OA_ACCOUNT_KEY` at
`backend/app/channels/types.py:370`) rendered "Zalo OA". With the TingTing OA
filter active, every row still read "Zalo OA" — it looked like the filter did
nothing. The filter chain itself was correct and is unchanged.

## Fix

One pure resolution point; every display surface keys off the resolved channel.

- **New** `frontend/src/components/atomic-crm/conversations/domain/conversation-channel-display.ts`
  — `resolveConversationDisplayChannel(identity)`: `zalo_oa` +
  `account_key === "tingting"` → the dedicated `tingting_oa` display channel;
  any other row keeps its raw provider; unknown/absent → `null` (callers keep
  their neutral "Kênh khác" fallback). The `tingting` literal is documented as
  a frontend copy of the backend constant (domains cannot import across the
  stack boundary).
- `presentation/ConversationList.tsx` — row chip (`data-channel`, `title`,
  short label) now uses the resolved channel. Bonus: the pre-existing but
  previously unreachable `[data-channel="tingting_oa"]` CSS rule in
  `conversations/inbox/conversation-list.css:473` now actually fires, so
  TingTing rows get their own chip styling.
- `presentation/ConversationShow.tsx` — header glyph (`channelIcon`),
  `alt`/`title`, short label and `data-channel` use the resolved channel, so
  the detail view shows the tingting-oa icon and "TingTing OA".
- `types.ts` label maps (keys unchanged): `CONVERSATION_CHANNEL_LABELS.tingting_oa`
  "Zalo OA TingTing (hỗ trợ nhân viên)" → **"TingTing OA"**;
  `CONVERSATION_CHANNEL_SHORT_LABELS.tingting_oa` "TingTing" → **"TingTing OA"**.
  "Zalo Chatbot"/"Chatbot", "Zalo OA", "Messenger" untouched as instructed.
- `ChannelAdapterSelector.tsx` — **no code change needed**: all four buttons
  already had distinct icons (`CHANNEL_ICONS`) and accessible names/tooltips
  from `CONVERSATION_CHANNEL_LABELS`; the label-value change makes the fourth
  read "TingTing OA — N hội thoại cần phản hồi".
- Tests: new `domain/conversation-channel-display.test.ts` (6 cases: default
  account → "Zalo OA", tingting → "TingTing OA", missing account_key, passthrough
  zalo_bot/messenger, already-narrowed identity, null/unknown fallbacks).
  `ChannelAdapterSelector.test.tsx`: the two `/Zalo OA TingTing/` name regexes
  updated to `/TingTing OA/` (label value changed; nothing else).

## Ripple (out-of-territory surfaces, vocabulary consumers only)

`notifications-menu.tsx`, `personas/domain/assignmentState.ts` and
`performance/.../AdapterComparison.tsx` read the same maps, so they now display
"TingTing OA" where they showed "Zalo OA TingTing (hỗ trợ nhân viên)". Files
untouched (outside territory); crisper consistent naming is the intent of the
shared-vocabulary contract in types.ts.

## Verification (from `frontend/`)

| Command | Result |
|---|---|
| `npm run typecheck` | pass (no errors) |
| `npx vitest --config vitest.config.ts --project app run src/components/atomic-crm/conversations` | 23 files / 138 tests passed |
| re-run post-prettier: helper + selector test files | 2 files / 11 tests passed |
| `npx eslint <6 touched files>` | exit 0 |
| `npx prettier --check <6 touched files>` | clean (after `--write` on the 2 new files) |
| `npm run registry:check` | pass (249 files; new domain file already picked up by the glob manifest) |

Not run: full lint/prettier over the whole tree (parallel agents have in-flight
files outside this territory; scoped runs above are the meaningful signal).
No dev server started.

## Files changed

- `frontend/src/components/atomic-crm/conversations/domain/conversation-channel-display.ts` (new)
- `frontend/src/components/atomic-crm/conversations/domain/conversation-channel-display.test.ts` (new)
- `frontend/src/components/atomic-crm/conversations/presentation/ConversationList.tsx`
- `frontend/src/components/atomic-crm/conversations/presentation/ConversationShow.tsx`
- `frontend/src/components/atomic-crm/conversations/ChannelAdapterSelector.test.tsx`
- `frontend/src/components/atomic-crm/types.ts`

Not committed (controller commits). `frontend/registry.json` was already
modified in the shared tree and covers the new file via the standard globs.

Status: DONE
Summary: OA rows now resolve their display channel from provider + account_key, so TingTing OA rows read "TingTing OA" with the tingting glyph in the list, the detail header and the filter tooltip; filter chain untouched.
Concerns: label-value ripple to notifications/personas/performance surfaces (files untouched, strings now "TingTing OA").
