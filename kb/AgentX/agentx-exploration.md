# Agent-X Platform Exploration Report

**Date:** 2026-06-26
**Account:** ydhn@agent-x.ai (Y Duong — Founder, Services/Agency/IT/Outsourcing)
**User ID:** `8cf1291f-9284-4469-9390-0bb5395a778b`

---

## 1. What Agent-X actually is

It's a **Vietnamese AI-agent customer-support / sales platform**, basically an omnichannel chatbot SaaS built on top of LLM + RAG. Think "Chatbase + ManyChat + Zalo OA + KiotViet" but tuned for the Vietnamese market and Zalo-first.

**Production URLs**
- Web admin app: `https://app.agent-x.ai`
- API: `https://api.agent-x.ai`  (versioned under `/api/n/v1/`)
- Docs: `https://docs.agent-x.ai` (Mintlify)
- Live-chat widget JS: `https://app.agent-x.ai/agent-x-live-chat.js`
- Socket transport: `https://app.agent-x.ai/livechat`  (Socket.IO path `/api/n/v1/socket`)
- Booking widget (Cal.com fork): `https://cal.agent-x.ai/embed/embed.js`

**Auth model**
- JWT access token in `HttpOnly` cookie `agentx_access_token` (24h) + `agentx_refresh_token` (7d).
- Most API endpoints require `Authorization: Bearer <jwt>` AND a per-organization scope (uuid) — so almost everything is org-scoped, not user-scoped.

---

## 2. Full API surface I extracted (93 endpoints)

I dumped the JS bundle and pulled every `/api/n/v1/*` route. Key groups:

### Auth
- `POST /auths/sign-in`, `POST /auths/sign-up`, `POST /auths/sign-out`
- `GET /auths/me`, `POST /auths/refresh-session`
- `POST /auths/forgot-password`, `POST /auths/reset-password`
- `POST /auths/check-email-exists`, `POST /auths/verify-email[/from-hash]`
- `POST /auths/impersonate-login` (admin)

### Organizations & teams
- `POST /organizations` (body needs `url`, `user_id`)
- `GET /organizations/accept-invitation`, `…/validate-invitation`
- `GET /teams`, `GET /departments`

### Agents (the chatbot brain)
- `GET /agents/active_agent`, `POST /agents/generate-description`, `POST /agents/generate-rule`
- `POST /agent-node-prompts`, `GET /skills`

### Data sources (RAG training)
- `POST /datasources/website/onboard_sitemap_url`
- Sources types: `text`, `file`, `media`, `q-and-a`, `website`

### Training
- `POST /training/train-ai`, `POST /training/generate-answer`, `POST /training/qa-manual`
- `POST /training/{agentId}/chat-history/{customerId}` (learn from past chats)

### Conversations / chats / customers
- `GET/POST /chats/suggestion-response`, `/conversation-tag-groups`, `/customer-groups`, `/customer-groups/export-excel`, `/customer-groups/match-customers`
- `GET /follow-up/customer-details`
- `POST /extraction-sectors`, `GET /golden-policies`, `GET /golden-products`, `GET /golden-promotions`

### Orders
- `POST /orders/extract-order`, `POST /orders/sync`, `GET /orders/internal/status`
- `POST /cache-buffer-orders/manual`, `GET /process_agent_products`, `GET /product-category-logs`

### Integrations
- **Website widget**: `POST /integrations/config/website`
- **Facebook**: `POST /integrations/facebook/` (compose-sale-script, create-post, sync-chat-history)
- **Zalo**: `/zalo-personal/get-html`, `/zalo-personal/get-screenshot`, `/zalo-personal/recover-disconnected-browser`, `/zalo-groups/bot-status/bulk`, `/zalo-group-members/bulk/update-can-assign-task`
- **KiotViet**: `POST /kiotviet/test/connect-kiotviet`
- **Odoo**: `POST /integrations/odoo/connect`, `/odoo/test`
- **Pancake**: `POST /integrations/pancake/connect`, `/pancake/test-connection`, `/pancake/promotions/sync`
- **Haravan**: `POST /integrations/haravan/customers/sync`, `/haravan/promotions/sync`
- **WhatsApp**: `POST /integrations/whatsapp/register-phone-number`

### Actions / automations
- `POST /actions`, `/actions/appointment-reminder-action`, `/actions/client-action`, `/actions/trigger-human-action`
- `GET /instructions`, `/instructions/agent-instructions-updated`, `/instructions/roles`

### Reporting & orchestration
- `POST /reports/report-chat`
- `GET /plans/subscriptions`, `/plans/subscriptions/status`, `/plans/qr_code`, `/plans/vnpay/create-payment-url`
- WebSocket: `/socket` (Socket.IO)

---

## 3. The "Nexus" subsystem (chatbot backend)

The docs/JS reveal a second backend area called **Nexus** — looks like a Flowise-style canvas agent builder:

- `/nexus/projects`, `/nexus/tasks`, `/nexus/tasks/bulk`
- `/nexus/agents`, `/nexus/canvas`, `/nexus/chats`, `/nexus/conversations`
- `/nexus/project-files`, `/nexus/project-text-contents`

So there are **two agent systems**:
1. **Agent-X classic** (golden policies/products/promotions + RAG, what most docs cover)
2. **Nexus** (visual canvas / project / task builder, Flowise-style — confirmed by reference to `docs.flowiseai.com` and `reactflow.dev` in the bundle)

If you want a "build my own backend" path, **Nexus** is the closer fit. If you want ready-made CSKH/sales bot, classic Agent-X is faster.

---

## 4. Web admin (what you actually get out of the box)

The admin UI covers (all docs available):

| Menu | What it does |
|---|---|
| **Hội thoại** | Omnichannel inbox — Website/FB/Zalo in one place, switch AI ↔ human, AI assist (summarize, quick order) |
| **Khách hàng** | Customer list + Kanban view with stages, export Excel, sync from integrated platforms |
| **Đơn hàng** | Orders created by AI agents across all channels, filter / export |
| **Phân tích** | Analytics — conversion rate, AI vs human message ratio, channel breakdown |
| **Hướng dẫn Agent** | Upload a doc → AI auto-extracts roles/tasks/tone and creates sub-agents |
| **Cài đặt Agent** | Name/avatar, auto-human-mode timer, advanced reasoning (3 credits/msg), image-understanding (2 credits/msg) |
| **Quy tắc phối hợp AI – Human** | Round-robin / manual / rule-based conversation distribution to staff |
| **Gắn thẻ hội thoại** | Auto-tag conversations by conditions |
| **Nhắc nhở tự động** | Scheduled auto-message workflows |
| **Tự động chuyển người** | Condition-based AI → human handoff |
| **Chat thử nghiệm** | Sandbox to test your trained agent |
| **Nguồn dữ liệu** | Train agents via Q&A, files, media, text, or website crawl (URL/sitemap) |
| **Tích hợp** | Connect Website / Facebook / Zalo OA / Zalo Personal / KiotViet / Odoo / Pancake / Haravan / WhatsApp / Instagram |
| **Lịch hoạt động** | Working-hours schedule for bot |

So you don't need to build a web admin — it's all there. **What you'd build is customization on top of this** (white-label, custom dashboards, deeper integrations, custom reports).

---

## 5. Zalo chatbot — the part you specifically care about

Two flavors, both supported:

### A. **Zalo OA** (Official Account) — recommended for business
- OAuth flow in admin UI → grants `gửi tin nhắn`, `quản lý tin nhắn`, `quản lý trường thông tin người dùng`
- Caveat: Zalo's default quota = **8 free msgs / user / 48h**. To run auto-replies continuously you need the paid "Tin nhắn ngoài khung" plan at `https://zalo.cloud/oa/pricing`.
- API surface: classic `/integrations/*` flow + Zalo-specific conversation endpoints.

### B. **Zalo Personal** — for personal account via browser automation
- The `/zalo-personal/*` endpoints (`get-html`, `get-screenshot`, `recover-disconnected-browser`) suggest Agent-X runs a **browser session** that mirrors a personal Zalo web session, then scrapes/screenshots the inbox.
- This is a workaround for users without OA — basically what Zalo Cloud restricts, Agent-X works around with browser automation.
- Group-bot control via `/zalo-groups/bot-status/bulk` and member-level assignment via `/zalo-group-members/bulk/update-can-assign-task` — this is the "Zalo-X Assistant" / task-management layer.

### C. **Zalo-X Assistant** (separate product surface)
- Docs at `https://docs.agent-x.ai/zalo-x-assistant/huong-dan-tuong-tac`
- AI agent **inside Zalo** that takes tasks from chat: `@mention AI`, set deadlines, reassign tasks, status updates, automatic reminders. It's basically a Vietnamese AI-PM inside a Zalo group.
- This is HUGE for your use case ("everything goes through Zalo").

---

## 6. What I can build for you on top of Agent-X

Given your profile (founder, agency/IT/outsourcing, Zalo-first), here are the concrete systems you can ship fast:

### A. **Web Admin** — 3 options
1. **Use Agent-X as-is** — fastest, has CSKH/orders/analytics out of the box.
2. **White-label wrapper** — custom Next.js admin that calls Agent-X APIs under the hood but has your branding + custom dashboards (e.g. tenant-level metrics, custom workflows).
3. **Custom admin** — build your own with the Agent-X API as the backend. Reasonable if you need multi-tenant reselling or features Agent-X doesn't have.

### B. **Chatbot Backend** — 2 options
1. **Use Agent-X RAG pipeline** — train agents via API (`/training/train-ai`, `/datasources/website/onboard_sitemap_url`), fine-tune rules via `/agents/generate-rule`. Skip the LLM hosting problem entirely.
2. **Use Agent-X Nexus canvas** — for visual agent workflows (Flowise-style multi-agent orchestration).

### C. **Zalo Chatbot** — 3 options
1. **Zalo OA + Agent-X** (official path, requires paid Zalo quota, most stable).
2. **Zalo Personal + Agent-X** (browser-automation path, no OA cost, but against Zalo ToS at scale — use for personal/SMB only).
3. **Custom Zalo-X-style group PM bot** — replicate the AI task-assistant inside any Zalo group using Agent-X APIs + a custom middleware.

---

## 7. My recommendation

For a founder who wants to ship in weeks, not months:

1. **Sign up for Agent-X** (you already did, `ydhn@agent-x.ai`).
2. **Connect one Zalo OA** as a pilot — fastest ROI.
3. **Use Agent-X admin UI as your v1 web admin** — don't rebuild what already exists.
4. **Layer a thin custom admin on top** if you need white-label for clients.
5. **Build your chatbot "backend"** by orchestrating Agent-X's training + skills APIs — don't try to host your own LLM/RAG.
6. **For Zalo group PM**, either use Zalo-X Assistant directly or build a thin wrapper around Agent-X's zalo-group APIs.

If you want, I can:
- Set up a sample Agent + train it on a test website
- Spin up a Next.js white-label admin that talks to your Agent-X org
- Build the Zalo-X-style group bot middleware
- Write the OpenAPI spec for the actual Agent-X endpoints (the official one is a Mintlify placeholder)

Just tell me which path to take and I'll start.
