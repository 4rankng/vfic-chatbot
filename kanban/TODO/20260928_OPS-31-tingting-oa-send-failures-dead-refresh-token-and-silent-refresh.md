---
id: OPS-31
title: "TingTing OA sends failed with 'Access token has expired' and no retry: stored refresh token is dead (Zalo -14014 Invalid refresh token); refresh failures were silent"
severity: high
area: backend
labels: [zalo, outbox, observability, credentials, production-incident]
effort: S
status: qa_tested
column: QA_TESTED
opened: 2026-09-28
---

# OPS-31 — TingTing OA sends failed with 'Access token has expired'; stored refresh token dead (Zalo -14014); refresh failures were silent

**Severity:** high · **Area:** backend · **Labels:** zalo, outbox, observability, credentials, production-incident

**Trạng thái:** QA_TESTED — code observability fix implemented 2026-09-28 (169 tests green). **Operator action still required:** re-link the TingTing OA credentials in the admin settings page; then retry the 3 dead messages from the console ("Thử lại").

## Problem

Production 2026-09-28, conversation `79fb0634-22bc-48c7-a2fd-a0560b2f664d` (TingTing
support OA, employee "Hoàng Tự" / recruiter Frank Ng): after the employee said
"Muốn đặt lại mật khẩu" (15:42) and the conversation was released back to the bot,
the three-field identity ask failed to deliver **three times** (15:49, 15:53,
15:53 ICT — console showed "Gửi lỗi" and the banner "Zalo chưa nhận được tin nhắn").

## Root cause (verified on prod)

- Outbox rows 3561/3565/3566 → messages 5398/5402/5404, status **FAILED**,
  `attempts=1`, `last_error = "chunk 1/1 failed: Access token has expired"`.
- The `tingting` OA's access token had expired Zalo-side; the dispatch path's
  refresh-on-invalid-token retry (`ZaloOASender._post_with_refresh_timing` →
  `IntegrationSettingsService.refresh_oa_access_token("tingting")`) ran and its
  silent `return None` branch swallowed the reason — no log line, so the original
  error was recorded and the row terminalized.
- Live probe (masked script against the token endpoint) captured Zalo's actual
  rejection: **HTTP 200, `error=-14014`, "Invalid refresh token."** — the stored
  `zalo_oa_refresh_token:tingting` (written 2026-09-27 07:48:45Z, never rotated
  since) is dead Zalo-side: already redeemed elsewhere or expired. No code path
  can recover a dead refresh token.
- The recruitment OA (`default:zalo_oa`, rotated 2026-09-27 12:18Z) kept sending
  fine all day — failure isolated to the `tingting` account.

## Fix (implemented)

`backend/app/services/integration_settings/providers/zalo.py` — the silent failure
branches now log the reason with the provider's own error fields (body carries no
secrets):

- no stored refresh token → warning "zalo OA token refresh skipped: no stored
  refresh token (account_key=…) — re-link the OA in settings";
- provider rejection → warning with `error` / `error_name` /
  `error_description` (e.g. `-14014 / Invalid refresh token.`);
- the lock-timeout and transport branches already logged.

### Link-time rotation — why a dead pair was storable (2026-09-28)

The renewal path itself was always correct: `refresh_oa_access_token` is
account-scoped, writes **both** rotated tokens, and commits before audit/cache
work. What the `tingting` account never had was a *proof* that the pasted pair
worked — `TingtingOaLinkService.link()` only probed the access token with
`getoa`, so a mismatched or already-redeemed pair was stored, audited
`verified: true` and activated, then failed at the first refresh ~25 h later.
That is precisely the 09-27 07:48 → 09-28 15:49 timeline.

`backend/app/services/tingting_oa.py`:

- `link()` now rotates **once** through the same provider call the default OA
  uses, always scoped to `tingting`. A Zalo refresh token is single-use, so the
  previous two-rotation shape burned two; the rotated token is reused for the
  re-probe when the first probe failed.
- A rejected rotation fails the link loudly with the `-14014` dashboard
  guidance, so the operator sees it at link time instead of a day later.
- A link now **requires** a refresh token; an access-token-only paste is refused
  up front with a clear message. This is the behaviour change that prevents a
  repeat of this incident.
- The staged credential write is flushed explicitly before the rotation, which
  reads it back through a SELECT — previously correct only by virtue of session
  autoflush.
- `_probe` redacts every credential in play (posted, stored, rotated) from both
  the provider's error text **and** the exception text, which previously
  redacted nothing. `oa_last_error` is admin-visible and persisted in
  `channel_account.provider_metadata`.

### The silent refresh (the `Test connection` burner)

`probe_zalo_oa_channel` redeemed the **default** OA's single-use refresh token a
second time purely to diagnose the secret key, then discarded the pair Zalo
issued and kept only a boolean. This did not cause the TingTing outage — the
probe is scoped to the default account — but one admin click while the
recruitment OA's token was expired would have killed that OA the same way.

`backend/app/services/integrations/zalo_diagnostics.py` no longer performs that
second grant. It delegates the one redemption to the provider (which persists
whatever it is issued) and reports the actionable conclusion instead;
`oa_secret_valid` is now `None` ("not determined without redeeming"). Guarded by
`backend/tests/test_zalo_oa_channel_probe.py`, including a structural check that
the module holds no token endpoint of its own.

## Operator action (BLOCKING for this conversation)

1. Admin → integration settings → re-link/refresh the **Ting Ting Software
   Solution** OA (fresh authorization so Zalo issues a new access+refresh pair).
   All four values must come from the same authorization — a mismatched set is
   what `-14014` means. Pasting an already-redeemed refresh token will re-create
   this incident, and the new link gate will now reject it immediately with the
   same guidance instead of storing it.
2. After re-linking, retry messages 5398/5402/5404 from the console ("Thử lại")
   so the employee gets the reset-flow ask.
3. Do not use "Kiểm tra kết nối" on the Zalo channel card as a way to renew
   TingTing: that probe is scoped to the default (recruitment) OA only.

## Notes

- The 7-minute gap between the 15:42 intent and the 15:49 send is the human
  takeover/release flow ("Frank Ng đã tiếp nhận hội thoại" → "trả lại cho chatbot")
  — working as designed, not part of this bug.
- Related: BOT-01 (the same conversation hit the premature-escalation bug earlier
  the same day; the login-trouble intent fix shipped with it).

---

_Opened 2026-09-28 from the delivery-failure investigation. Evidence: outbox rows, live token-endpoint probe, credential staleness query — all on prod._
