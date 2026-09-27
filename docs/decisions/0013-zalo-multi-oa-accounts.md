# ADR-0013: A second Zalo OA is a first-class channel account

- **Status:** Accepted
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

1. **Per-account credentials in the existing namespace.** An additional OA stores
   the same four credentials under `zalo_oa_*:<oa id>` (mirroring
   `facebook_page_token:<page id>`). `resolve_zalo(account_key)` returns an
   account's own values; a **non-default account never inherits the singletons or
   the env fallback** — missing credentials resolve empty and the senders fail
   closed, because a reply leaving as the wrong brand is worse than a failed send.
2. **Routing by `oa_id`.** `POST /webhooks/zalo/oa` resolves the receiving OA from
   the body (`oa_id`, falling back to the recipient id) to a linked, ACTIVE
   `zalo_oa` channel account. An absent or unknown id resolves to `default:zalo_oa`
   — today's behaviour — so an unlinked OA or a payload-shape change degrades to
   the single-OA path instead of dropping events. The key threads through
   `run_zalo_ingress` → `ZaloWebhookService.handle` → `ensure(...)` and the OA
   side-event handler, so contact identities, conversations, receipts and
   enrichment all belong to the OA that received the event.
3. **Sending as the receiving OA.** The graph turn resolves the conversation's
   account key (`resolve_zalo_account_key`) and binds the Zalo config (and the
   refresh closure) to it; the outbox dispatcher resolves the same key from the
   message's conversation identity; the OA channel adapter scopes receipts to the
   account it was built for.
4. **Refresh is per account.** Each OA has its own single-use refresh token, so
   the lock key and the rotated keys are account-scoped
   (`zalo:oa:token:refresh:<oa id>`). Sharing one lock would let one OA's refresh
   block another's.
5. **Linking is explicit and reversible.** `POST /admin/integrations/zalo/oa-accounts`
   (with `oa_id` + credentials; an access token is required) creates or
   reactivates the channel account and bumps its generation, which fences
   outbound work queued under the previous credentials.
   `DELETE .../zalo/oa-accounts/{account_key}` marks it INACTIVE and **deletes**
   the stored credentials: history stays readable, but no token remains that could
   send as that OA. The seeded original OA cannot be unlinked.
6. **No re-keying of existing data.** Contacts, conversations and messages stay on
   the account key that created them. Backfilling the original OA's history onto a
   real OA id would split identity rows
   (`uq_contact_channel_authority (provider, account_key, external_id)`) and orphan
   live conversations. Linking the **original** OA under its own OA id would do
   exactly that to every future event, so `link` refuses an access token equal to
   the stored original OA's token ("this token belongs to the OA already
   configured") — the same token identifies the same OA.
7. **The reset flow pin now has something to point at.** `tingting_reset_oa_id`
   (ADR-0012 §12) accepts the linked account key, so the flow runs only on the
   TingTing OA once the operator links it.

## Consequences

- A single-OA deployment is byte-identical: the default account, the Bot channel
  and Messenger keep their paths, and no event changes hands.
- OA credentials remain server-side and encrypted; the admin API only ever returns
  `{configured, preview}` status, and the settings page never renders a value.
- Linking a second OA is one admin action; the OA id becomes the account key, so a
  wrong id shows up as events still landing on the original OA rather than as a
  silent mis-route.
- Unlinking is a credential-destroying action, so a mistaken unlink requires
  re-entering the OA's tokens from the Zalo console (no stored copy remains).
- The registry still keys adapters by provider: one dispatch resolves one account's
  config and therefore needs exactly one OA adapter. Should a future surface need
  to fan out to several accounts in a single dispatch, the registry key must gain
  the account key.
- Previewing/receiving on the linked OA requires that OA's own credentials from the
  Zalo console; the flow cannot be exercised end-to-end without them.
