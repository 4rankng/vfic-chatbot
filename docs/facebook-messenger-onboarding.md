# Facebook Messenger Page onboarding runbook

How to connect ONE Facebook Page to the chatbot — including a customer Page
migrating from another platform (e.g. Pancake) — and how to roll back.

Scope: the platform currently supports **one active Page** at a time. Activating
a new Page archives the previously active Page (its conversations and history
are preserved, read-only). Multi-Page support is deferred.

## 1. Prerequisites (Meta side, operator)

| Item | Requirement |
|---|---|
| Meta app | "TingHire Messenger" (App ID `1052965677598216`) with Facebook Login for Business + Messenger/Webhooks configured. |
| Business verification | Done through the Business Portfolio "TingTing Soft" (ID `1091256110292973`). Required for App Review. |
| App mode | For a Page you do **not** own, the app must be **Live** with App Review approval (advanced access) for `pages_messaging` (+ `pages_show_list`, `pages_manage_metadata`). In Development mode only app-role users (admin/dev/tester) can chat with the bot — everyone else's messages are silently dropped by Meta. |
| App webhook | Callback URL `https://<backend-host>/webhooks/facebook`, verify token = the value configured in CRM Settings → Facebook Messenger → "Verify Token". Subscribe to the `messages` and `messaging_postbacks` fields (matches what the connect flow requests per Page). |
| App credentials | CRM Settings → Facebook Messenger: App ID, App Secret, Verify Token (DB-first, env fallback). No secrets in this doc. |

Anti-hijack note: a Facebook account that became a Page admin **less than 7
days ago** cannot approve adding that Page to a Business Manager (this blocked
the TingTing Soft Page until Mon 2026-09-07 ~18:57). This restriction applies
to Business-Manager linking only — the OAuth connect path below is not
affected.

## 2. Customer-side steps (send this to the Page owner)

> **Gỡ chatbot cũ và cấp quyền cho bot mới (Facebook):**
>
> 1. Vào **Pancake** (hoặc nền tảng chatbot cũ) → gỡ/ngắt kết nối Trang khỏi
>    Pancake. *Bước này bắt buộc trước khi bật bot mới — nếu cả hai cùng kết
>    nối, cả hai cùng trả lời tin nhắn.*
> 2. Kiểm tra **Cài đặt Trang → Tích hợp/Apps** và xoá ứng dụng của nền tảng
>    cũ nếu còn.
> 3. Đảm bảo tài khoản Facebook của bạn có quyền **quyền kiểm soát đầy đủ**
>    với Trang (Settings → New Pages Experience → Page access).
> 4. Khi bên tụi mình gửi bước kết nối: đăng nhập Facebook bằng tài khoản của
>    bạn trong cửa sổ cấp quyền, chọn Trang cần nối, và nhấn cho phép các
>    quyền được yêu cầu.
> 5. Sau khi kích hoạt, nhắn thử 1 tin vào Trang để kiểm tra bot trả lời.

## 3. Operator steps (CRM)

Order matters: persona/KB first, remove Pancake first, then connect.

1. **Prepare the bot identity.** Personas → configure the Agent used by the
   `facebook_messenger` adapter (persona + knowledge base) for the customer's
   business. With one active Page, the adapter-level override (or the global
   default Agent) is what answers — there is no per-Page override yet.
2. **Confirm the customer removed Pancake** (step 2 above).
3. **Connect the Page.** Settings → Facebook Messenger → "Kết nối Facebook" →
   complete the Facebook Login dialog (the Page owner enters their
   credentials in the dialog) → the CRM shows the authorized Page list →
   select the customer Page → "Kích hoạt Trang".
   - This stores the Page access token (encrypted, Page-bound), **subscribes
     the app to the Page** for webhook events, and activates the channel
     account. Any previously active Page is archived (history preserved).
4. **Pre-cutover check.** Press "Kiểm tra kết nối". It must report healthy.
   The probe verifies: the Page token is valid AND the app is subscribed to
   the Page for webhook events. On "Ứng dụng chưa nhận sự kiện webhook từ
   Trang này" → "Ngắt kết nối" then connect again.
5. **Go-live test.** Have the Page owner (or a test user) message the Page →
   the bot replies and the conversation appears in Conversations.

## 4. Operational behavior

- **24-hour window.** Meta's standard messaging window is enforced server-side
  on every outbound; outside the window the reply is suppressed
  (`policy_suppressed`). No message tags (e.g. `HUMAN_AGENT`) are supported
  yet.
- **Human takeover.** Recruiters take over a conversation in the CRM; the bot
  stands down per the usual mode guards.
- **Identity.** Messenger PSIDs are Page-scoped; the API only ever exposes a
  masked suffix.
- **Receipts.** Delivery/read receipts are applied best-effort when Meta
  delivers them; they never block the webhook ack.

## 5. Rollback (back to Pancake)

1. CRM Settings → Facebook Messenger → "Ngắt kết nối". This unsubscribes the
   app from the Page (best-effort) and marks the Page inactive; conversations
   and history are kept.
2. The customer reconnects the Page in Pancake.
3. Optional: rotate the Verify Token (Settings) and re-register the app
   webhook if the token was shared.

## 6. Verification checklist (pre-cutover)

- [ ] Meta app Live + App Review approved for `pages_messaging` (external Pages)
- [ ] Business verification completed (Business Portfolio)
- [ ] App webhook registered with correct verify token
- [ ] Customer removed the old platform from the Page
- [ ] Persona/KB configured for the customer's business
- [ ] "Kiểm tra kết nối" healthy (token + webhook subscription)
- [ ] First-message test answered and visible in Conversations
