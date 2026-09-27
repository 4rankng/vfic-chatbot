# Facebook Messenger Page onboarding runbook

How to connect Facebook Pages to the chatbot — including customer Pages
migrating from another platform (e.g. Pancake) — and how to roll back.

Scope: the platform supports **multiple simultaneously-active Pages**. Each
Page is assigned its own subset of Projects, and a conversation only ever
offers the Projects assigned to the Page it came from. Activating a new Page
no longer archives other active Pages (existing Pages keep running
untouched); disconnecting a Page keeps its conversations and history.

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
   business. The adapter-level override (or the global default Agent) answers
   on every Page — there is no per-Page persona override (recorded decision:
   Project scoping is the isolation mechanism).
2. **Confirm the customer removed Pancake** (step 2 above).
3. **Connect the Page.** Settings → Facebook Messenger → the connected-Pages
   list → "Kết nối Facebook" (adds another Page; existing Pages are not
   affected) → complete the Facebook Login dialog (the Page owner enters
   their credentials in the dialog) → the CRM shows the authorized Page
   list → select the customer Page → "Kích hoạt Trang".
   - This stores the Page access token (encrypted, Page-bound), **subscribes
     the app to the Page** for webhook events, and activates the channel
     account. Other connected Pages keep running untouched.
   - A Page cannot be activated with zero assigned Projects — assign
     Projects first (§3.1).
4. **Pre-cutover check.** Press "Kiểm tra kết nối". It must report healthy.
   The probe verifies: the Page token is valid AND the app is subscribed to
   the Page for webhook events. On "Ứng dụng chưa nhận sự kiện webhook từ
   Trang này" → "Ngắt kết nối" then connect again.
5. **Go-live test.** Have the Page owner (or a test user) message the Page →
   the bot replies and the conversation appears in Conversations.

### 3.1 Multi-Page: adding a Page and assigning its Projects

1. **Assign Projects first.** Each connected Page has a Project editor
   (multi-select) on the Messenger settings page. A Page cannot be activated
   with zero Projects — this prevents a Page from answering candidates with
   an empty or wrong-customer catalog.
2. **Add the Page** (step 3 above). Connecting a new Page never disrupts
   existing Pages.
3. **Verify webhook routing.** Message the NEW Page → the bot must reply and
   the conversation must appear under the new Page. Inbound events are
   routed by the event's own Page id, so a message sent to Page A only ever
   surfaces Page A's assigned Projects.
4. **Regression-check an existing Page** after connecting a new one: its
   conversations still answer with its own assigned Projects.

Backfill note: the rollout migration assigned all currently-active Projects
to the platform's pre-existing active Page, so that Page's behavior is
unchanged by the rollout.

Disconnecting a Page ("Ngắt kết nối") keeps its Project assignments —
reconnecting restores the catalog as configured (recorded decision D6).
Assignments are only removed explicitly, via the Project editor.

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
- [ ] Page has ≥1 Project assigned (activation is blocked otherwise)
- [ ] Multi-Page regression: existing Pages unaffected after connecting a new one
- [ ] New Page's test message answered and routed to the new Page's Projects

## 7. Phase 0 / platform configuration notes (do not lose these)

These were real blockers hit while connecting the first Pages (September
2026); they are configuration, not code — losing one silently re-breaks
every Page connection.

- **`FACEBOOK_CALLBACK_ALLOWLIST`.** The backend builds the OAuth redirect
  URL from this allowlist (`backend/app/core/config.py`); if the env var is
  missing it falls back to `http://localhost:5173` and every OAuth attempt
  redirects to localhost. Prod `/opt/vfic/.env` carries
  `FACEBOOK_CALLBACK_ALLOWLIST=["https://bot.tingting.vip"]`. Note:
  `scripts/prod-env.sh` does not template this key, so regenerating `.env`
  from scratch reintroduces the bug until the key is re-added.
- **Meta App Dashboard.** The app needs both "App Domains" (Basic Settings)
  and "Valid OAuth Redirect URIs" (Facebook Login for Business → Settings;
  Strict Mode is on) set to `bot.tingting.vip` / the exact callback URL.
  Empty fields block the OAuth dialog with "Can't load URL" — independent
  of anything in our code.
- **Development-mode Tester requirement.** While "TingHire Messenger" is
  Unpublished, any Facebook account completing OAuth must hold an
  Admin/Developer/Tester role on the Meta app **in addition to** being an
  admin of the target Page. Standing decision (2026-09-08): onboard each new
  Page operator as a Tester; revisit App Review + Publish before onboarding
  scales past a handful of customers.
- **Account-confirmation checkpoint.** Meta can put an operator's own
  account into an "Account confirmation needed" / unusual-activity
  checkpoint that blocks all developer-platform actions, including OAuth for
  an app it administers. Resolve it in Facebook's own recovery flow — it is
  not a bug on our side.
- **Service worker / OAuth callback.** The SPA's service worker must never
  intercept top-level navigations to `/api/*` — Facebook's OAuth redirect is
  such a navigation, and a SW serving the cached app shell for it makes the
  callback hang forever with zero network requests. The Workbox config
  (`frontend/vite.config.ts`) carries `navigateFallbackDenylist` for `/api/`,
  `/webhooks/`, `/realtime/`, `/socket.io/`; if the PWA config is ever
  reworked, this denylist must survive it. Repro check: direct browser
  navigation to `/api/v1/health` must show the JSON 404, never the
  "Đang tải…" spinner.
