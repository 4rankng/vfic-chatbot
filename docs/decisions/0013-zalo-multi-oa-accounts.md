# ADR-0013: A second Zalo OA is a first-class channel account

- **Status:** Accepted (serving policy in point 6 amended 2026-09-27)
- **Date:** 2026-09-27
- **Decider:** Product owner / operator

## Context

The operator wants the employee password-reset flow (ADR-0012) served by a
**different** Zalo Official Account ("TingTing Software Solution") than the
existing OA the recruitment chatbot runs on, with an admin able to link that OA
from the settings page — "the same flow as the current OA".

The deployment had exactly one OA:

- `channel_accounts` holds one `zalo_oa` row, `default:zalo_oa` (Alembic 0047);
- its four credentials are singleton `integration_settings` keys
  (`zalo_oa_app_id/secret_key/access_token/refresh_token`);
- `POST /webhooks/zalo/oa` parses the event but never asks *which* OA it
  belongs to, and `BotConversationState.ensure` hardcoded `default:zalo_oa`;
- one `ZaloOASender` (built from one config) served every Zalo conversation, and
  the outbox dispatcher hardcoded the default account key;
- the OA token refresh used one lock and one stored refresh token.

So "link another OA" could not be done as a settings-only change: without
routing, a second OA's events would arrive on the original OA's identity and its
replies would leave with the original OA's token.

## Decision

1. **One linked support OA, configured like the existing OA.** The operator asked
   for "the same flow as the current OA": the TingTing card holds the same four
   fields (App ID, Secret Key, OA Access Token, OA Refresh Token) as the Zalo OA
   card. There is no "mã OA" field and no account-key field anywhere — a typed
   identifier was unreadable to the operator and easy to get wrong.
2. **Zalo names the OA.** Saving the four fields probes `getoa`
   (`TingtingOaLinkService`): the response carries the OA's own id and display
   name, which are stored in the support account's `provider_metadata`
   (id/name/verified_at, or a redacted `last_error`). A failed probe still stores
   what was typed — the admin fixes one field and saves again — but the account
   stays INACTIVE and the reset flow stays off, so a broken link can never serve
   employees. A cleared four-field submission unlinks (credentials destroyed).
3. **The account key is a constant, not the OA id.** The support account is
   `zalo_oa` / `tingting`, with credentials under the standard per-account
   namespace (`zalo_oa_*:tingting`), so `resolve_zalo("tingting")`, the per-account
   token refresh and the senders need no new plumbing. Inbound routing compares
   the event's OA id against the **registered** one:
   `ZaloOaAccountResolver.account_key_for_payload` → `tingting` on match,
   otherwise `default:zalo_oa` (today's behaviour, never a dropped event).
4. **Routing roles are kind-aware.** The OA id comes from the parsed event
   (`ZaloOAWebhookEvent.oa_id`): the root `oa_id` when Zalo sends it, else the
   sender for receipt events (roles invert there) and the recipient otherwise.
   Reading the recipient blindly matches a *user* id on receipts.
5. **The reset flow is bound to that account.** `_tingting_reset_allowed`
   requires provider `zalo_oa`, `account_key == "tingting"`, and the pin
   `tingting_reset_oa_id == "tingting"` — a value only a verified link writes, so
   the original OA, the recruitment Bot and Messenger can never serve the flow.
   The pin is no longer an admin field.
6. **Serving policy split.** On the support OA the bot serves the reset flow and
   nothing else: the bound tools are the TingTing reset tools (no project
   knowledge, no recruiting catalog). An employee who has **not said what they
   need** — only a greeting, "tôi cần hỗ trợ", "app bị lỗi", or a reading Jev
   could not stand behind (`general`/`small_talk` below the route confidence
   floor) — is **asked which problem they have** by the bot, on the reset
   toolset, and stays with the bot so their answer starts the flow. Only a
   **confident non-support** question (recruitment/admin: pay, vacancies,
   shuttle, contact, out of scope) gets the fixed line "Vui lòng chờ chuyên viên
   tư vấn liên hệ." plus a handoff that flags the conversation for a human.
   Everywhere else, a reset request gets the fixed pointer to the support OA
   (`https://zalo.me/3383849659955472174`). Both strings are returned verbatim,
   never generated, so a paraphrase cannot drop the link or invent a hotline.
7. **Admin-only threads, out of the pipeline.** The support OA carries staff
   password resets, not candidates: `viewer_scope.py` gains a correlated
   `NOT EXISTS` on the canonical identity, applied through
   `viewer_conversation_filter` / `viewer_lead_filter` at every conversation and
   lead read (list, message page, counters, socket check, dashboard aggregates) —
   and its raw-SQL twins for the dashboard. Candidate extraction, the inbound
   deterministic name capture and proactive follow-ups are skipped on that
   account. Admins read those threads through a fourth badge on
   `/#/conversations` (`tingting_oa`), which filters by account key.
8. **No re-keying of existing data.** Contacts, conversations and messages stay on
   the account key that created them; the original OA's history is untouched. The
   support OA's own events were previously indistinguishable and are now routed to
   `tingting` — a new identity per employee on that OA, which is correct: those
   conversations never existed anywhere before.

## Consequences

- A single-OA deployment is byte-identical: the default account, the Bot channel
  and Messenger keep their paths, and no event changes hands.
- OA credentials remain server-side and encrypted; the admin API only ever returns
  `{configured, preview}` status, and the settings page never renders a value.
- Linking is one admin action (paste four fields, save): either the card reports
  "Đã liên kết: <OA name> (<OA id>)" or it reports why Zalo rejected the token.
  Nothing to type by hand, nothing to guess.
- Unlinking is a credential-destroying action, so a mistaken unlink requires
  re-entering the OA's tokens from the Zalo console (no stored copy remains).
- The registry still keys adapters by provider: one dispatch resolves one account's
  config and therefore needs exactly one OA adapter. Should a future surface need
  to fan out to several accounts in a single dispatch, the registry key must gain
  the account key.
- Previewing/receiving on the linked OA requires that OA's own credentials from the
  Zalo console; the flow cannot be exercised end-to-end without them.
- **Amendment (point 6, 2026-09-27).** The original "any non-reset message waits for
  a consultant" rule queued employees who had not yet said what they needed, and the
  escalation it performed invalidated the send claim of its own turn, so the line
  never reached them either (console: "Đã chặn"). Now the bot asks an unclear
  employee which problem they have and keeps the thread, so their answer starts the
  reset flow; only a confident non-support question still hands off, with the
  escalation demoted to a claim-preserving form
  (``escalate_extracted_intent(preserve_turn_ownership=True)``).
