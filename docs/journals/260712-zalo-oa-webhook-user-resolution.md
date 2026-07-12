---
title: "Zalo OA webhook user resolution — three bugs, one flawed assumption"
date: "2026-07-12"
status: resolved
scope: "backend/app/services/zalo_oa_events.py, conversation/state.py, webhook.py"
---

# Zalo OA webhook user resolution — three bugs, one flawed assumption

Commit: `5b7e64ec` on `main`, shipped via `make push` + `make deploy-restart`.

## Context

Live testing against the Zalo OA "Test" button (follow, unfollow,
user_received_message, user_seen_message) surfaced three related production bugs
in `parse_oa_webhook_event`. All three came from the same flawed assumption:
that the user id always lives under the `sender` key. It does not. Zalo puts it
in different keys depending on event kind, and inverts roles for receipts.

The brutal part: all 672 backend tests were green while every one of these bugs
was live. The tests were verifying a parallel universe.

## What happened

- **follow / unfollow — `follower` key ignored.** Zalo identifies the user under
  `follower` for lifecycle events, not `sender`. The parser returned an empty
  `sender_id`, so `scoped_chat_id` was empty, and `apply_follow` /
  `apply_unfollow` mutated a garbage conversation row with `zalo_chat_id=''`
  instead of the user's real `oa:<user_id>`. Confirmed in prod DB: a garbage row
  `ec5790a7-...` was being touched by every follow/unfollow test.
- **user_received / user_seen — receipts scoped to the OA, not the user.** Zalo
  inverts roles for receipts: `sender.id` is the OA, `recipient.id` is the user.
  But `scoped_chat_id` always used `sender_id`, so receipts were scoped to
  `oa:<OA_ID>` and `apply_delivery_receipt` never found the outbound Message.
  Each receipt test also created a fresh garbage OA-id conversation.
- **user_seen_message — `msg_ids` array not parsed.** This event carries
  `msg_ids` as an ARRAY (a user can see several messages at once); the parser
  only read a single `msg_id`. So `message_id` was always empty, the early guard
  in `apply_delivery_receipt` returned early, and seen receipts never advanced
  `delivery_status` — even after the scoping fix.

## Why CI missed all three

The existing tests used one uniform payload shape `{"sender": {"id":
"user-123"}}` across every event kind — a shape that only matches
`user_send_text`. Follow/unfollow tests used `sender` instead of `follower`;
receipt tests used `sender` as the user instead of `recipient`; no test ever
carried a `msg_ids` array. The suite was green because it was asserting against
the wrong contract, not because the code was right.

## Decisions

- Parser now falls back to `payload.get("follower")` for sender resolution, so
  follow/unfollow resolve the real user.
- `scoped_chat_id` uses `recipient_id` for receipt kinds and `sender_id`
  otherwise — explicit role handling instead of a single assumed key.
- New `event.message_ids` tuple, populated from the `msg_ids` array (deduped,
  order-preserved) or a single `msg_id`. The single-id `message_id` field stays
  for back-compat.
- Added `apply_delivery_receipt_batch` in `conversation/state.py`: one SELECT +
  one commit + one realtime emit for N messages. The old
  `apply_delivery_receipt` is now a 1-element wrapper so existing callers are
  unchanged.
- Rewrote the affected tests to use real Zalo payload shapes, with assertions on
  `scoped_chat_id` and `message_ids` — not just on side effects that would pass
  under the wrong contract.

## Verification on prod

After deploy, all four events were re-tested live and confirmed:
- follow → real conversation `oa:74247346174341218` updated, garbage row
  untouched.
- unfollow → `needs_human=True`, `followup_opted_out=True`, SYSTEM note on the
  real conversation.
- user_received_message → no garbage OA-id row created.
- user_seen_message → array parsed and deduped, scoped to the user correctly.

## The brutal truth

Early in the session the user said "I think you need to write code first before
[you] can test." I dismissed it — I had read the parser on the surface and
concluded no code change was needed. The user was right. The first live
button-press surfaced bugs that surface-level code review and 672 passing tests
both missed.

The lesson I am not allowed to forget: a green test suite is not evidence of
correctness when the tests encode the wrong assumptions about an external
contract. Integration testing against the real system caught in minutes what the
unit suite structurally could not. When a user who actually runs the system
tells you the tests are lying, believe them.

## Next

- Keep the rewritten Zalo-shape tests as the baseline; never regress payload
  shapes back to the uniform `sender`-only form.
- Audit other external-contract parsers (anything fed by a third-party
  webhook) for the same trap: do the unit-test payloads match the real upstream
  shape, or just the shape the parser happens to expect?
- Treat live OA test-button runs as a release gate for any webhook change, not
  an optional sanity check.
