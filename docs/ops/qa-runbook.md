# QA Runbook — Dev Environment

> **Audience:** AI coding agents (Claude Code, Codex, Gemini CLI) and humans
> performing manual + scripted QA against the local dev stack.
>
> **Purpose:** Tell you *exactly* how to QA the VFIC ATS recruiter console
> running at `http://localhost:5173/`, what to look for, and how to record
> findings so they are reproducible.
>
> **Scope:** The recruiter console (frontend SPA) and the API surface it
> touches. This runbook covers **visual/UI-UX QA**, **functional/logic QA via
> browser scripts**, and **latency/perf probing**. It complements
> [`docs/testing.md`](../development/testing.md) (automated unit/integration tests) and
> [`frontend/qa/TEST_PLAN.md`](../../frontend/qa/TEST_PLAN.md) (manual per-feature
> checklist) — it does **not** duplicate them.

---

## 1. Prerequisites & Dev Stack

### Bring up the stack

From the repository root:

```bash
make dev              # Postgres + Redis + Adminer + backend (uvicorn :8000)
                      #   + RQ workers + Zalo mock (:8788) + frontend (:5173)
```

If you only need the frontend hot-reloading against a running backend, from
`backend/` run `make dev` (same target, fewer surprises). `make dev` does not
seed: load the dev fixture data separately with `make seed` (which runs
`backend/scripts/seed_dev.py`).

### Verify the stack is up

| Check | Expected |
|-------|----------|
| `curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/` | `200` |
| `curl -s http://localhost:8000/health` | `{"status":"ok"}` |
| Frontend loads `#/login` when unauthenticated | Login form with email + password |

### Ports & services (dev defaults)

| Service | Port | Notes |
|---------|------|-------|
| Vite dev server (SPA) | `5173` | Proxies `/api`, `/realtime`, `/socket.io` → backend |
| FastAPI (uvicorn) | `8000` | `/api/v1/*` mount; `/health`, `/metrics` unprefixed |
| Postgres | `5432` | `vfic/vfic`, db `vfic` |
| Redis | `6379` | Cache + RQ broker + Socket.IO pub/sub |
| Adminer | `8082` (or `make adminer` → `localhost:18081` via tunnel) | DB UI |
| Zalo mock | `8788` | Local stand-in for Zalo OA API |

### Tooling for scripted QA

Two browser-automation paths are available. **Prefer `agent-browser`** for new
scripts — it is faster (Rust client) and already used by the
[`ck:agent-browser`](https://github.com/vercel-labs/agent-browser) skill.
Fall back to Playwright (already a project dev-dependency) only when you need
assertions inside a Vitest test.

```bash
# agent-browser (preferred for ad-hoc / scripted QA)
agent-browser --version              # verify install
agent-browser install                # one-time Chromium download

# Playwright (used by existing frontend/qa/*.cjs scripts)
cd frontend && npx playwright --version
```

Existing probe scripts live in [`frontend/qa/`](../frontend/qa/):
`qa-smoke.cjs`, `qa-audit.cjs`, `qa-audit2.cjs`, `probe-*.cjs`. Read them
before writing a new one — copy the established login + error-capture pattern
rather than reinventing it.

---

## 2. Test Credentials & Data Safety

### Accounts (seeded by `make db` → `scripts/seed_dev.py`)

| Email | Password | Role | Use for |
|-------|----------|------|---------|
| `admin@vfic.dev` | `admin123` | `admin` | **Primary QA account** — full access incl. `/hieu-suat` (performance) + `/users` |
| `lan.nguyen@vfic.dev` | `admin123` | recruiter | Role-gating checks (no admin routes) |
| `minh.tran@vfic.dev` | `admin123` | recruiter | Role-gating checks |

> `make reset-passwords` (root Makefile) resets **all** users to `admin123` and
> recreates admin if missing — use it when login starts failing.

### Data mutation rules (READ BEFORE ACTING)

1. **Prefix every temporary record with `QA`** and a timestamp slug, e.g.
   `QA-project-20260712-1530`, `QA-user-…@vfic.dev`. This makes cleanup and
   audit trivial.
2. **Never delete seed or business records.** In particular: `LG-DISPLAY`
   project, `faq-001-lg-display.md` knowledge source, and any real VFIC user.
   The TEST_PLAN calls these out explicitly.
3. **Never send test messages in a real candidate conversation thread.**
   Conversations are candidate-facing via Zalo. Use a dedicated QA conversation
   or the Zalo mock.
4. **Restore mutable state.** If you change a stage, mode, or profile field on
   a real record, restore the original value before ending the run.
5. **Clean up before exit.** Delete every `QA-*` record you created. The
   runbook's exit checklist (§7) enforces this.

### Auth flow (what the scripts need to replicate)

- **Endpoint:** `POST /api/v1/auth/login` body `{ email, password }`
- **Response:** `{ access_token, refresh_token, token_type, expires_in }`
- **Storage:** tokens land in `localStorage` under
  `RaStore.auth.access_token` / `RaStore.auth.refresh_token`
- **Identity:** `GET /api/v1/auth/me` is called right after login to cache
  permissions
- **Frontend selectors (stable):**
  - `input[name="email"]` (or `input[type="email"]`)
  - `input[name="password"]` (or `input[type="password"]`)
  - `button[type="submit"]`

---

## 3. What to Test — Routes & Features Map

The SPA is react-admin with hash routing. **All routes are `#/...`.** Below is
the canonical map; visit each on desktop **and** mobile (390×844) per run.

### Resource routes (react-admin)

| Route | Resource | Component | QA focus |
|-------|----------|-----------|----------|
| `#/` | — (dashboard) | `dashboard/Dashboard.tsx` | Cards render live values; no overflow; mobile stacks |
| `#/conversations` | `conversations` | `conversations/ConversationList.tsx` | Switch between the exclusive Zalo Chatbot/Zalo OA icon scopes; URL contains `channel_provider`; adapter badges and selected caption match scoped attention counts; search/queue/reason filters never mix adapters; a nonzero `Tin nhắn` badge opens `?needs_attention=true` and lists only open Human-mode conversations with an unanswered candidate message; Bot/Semi-auto rows stay out until transitioned to Human; mode menu (Human/Semi-auto/Chatbot); composer disabled in chatbot mode |
| `#/conversations/:id` | show | `conversations/ConversationShow.tsx` | Thread loads; context panel; takeover toggle; send (QA conv only) |
| `#/bot_runs` | `bot_runs` (read-only audit) | `automation/BotRunList.tsx` | Run cards: outcome, preview, timing; detail view |
| `#/projects` | `projects` | `projects/ProjectList.tsx` | CRUD cycle on a `QA-*` project; delete confirmation names target |
| `#/personas` | `personas` | `personas/PersonaList.tsx` | Active persona marked; create/edit; assignments |
| `#/users` | `users` (admin only) | `users/UserList.tsx` | List/sort/badges; create/edit/delete on `QA-*` user |
| `#/settings` | `settings` | `integrations/ZaloIntegrationPage.tsx` | Zalo OA config form renders; Messenger section renders on desktop/mobile; secrets masked |

### Custom routes

| Route | Component | QA focus |
|-------|-----------|----------|
| `#/hieu-suat` | `performance/PerformancePage.tsx` | **Admin-only** — recruiter role redirects to `/`. Empty states render. |
| `#/profile` | `settings/ProfilePage.tsx` | Save button disabled until dirty; restore original after |
| `#/forgot-password` | `login/ForgotPasswordPage.tsx` | 2-step OTP flow; no account-existence leak in messages |
| `#/login` | `login/LoginPage.tsx` | Email/password render; password toggle; invalid-creds toast; SSO hidden unless `VITE_GOOGLE_WORKPLACE_DOMAIN` set |

### Feature flags that change behavior

| Env var | Effect when set |
|---------|-----------------|
| `VITE_ATTENTION_DASHBOARD_ENABLED=false` | Disables dashboard attention section |
| `VITE_GOOGLE_WORKPLACE_DOMAIN=<domain>` | Shows Google SSO button on login |
| `VITE_DISABLE_EMAIL_PASSWORD_AUTHENTICATION=true` | Hides email/password form (SSO-only) |

If a feature looks missing during QA, check these before filing a bug.

### 3.1 Messenger Settings smoke

Use this when touching the Messenger Settings flow or its backend OAuth
lifecycle.

1. Open `#/settings` on desktop and mobile. Confirm both Zalo and Messenger
   sections render in the side nav or drawer.
2. Visit a callback-shaped hash such as
   `#/settings?facebook_oauth_status=pending_selection&facebook_oauth_flow_id=<opaque>`.
   Confirm the Messenger section opens, the page list loads, and the hash is
   cleaned back to `#/settings` after the callback is consumed.
3. Trigger the error path with
   `facebook_oauth_status=error&facebook_oauth_error=<code>` and confirm the
   alert stays generic Vietnamese text with no token, code, or provider payload
   leakage.
4. Click `Ngắt kết nối` and confirm the browser sends
   `DELETE /api/v1/admin/integrations/facebook` with no `page_id` query
   parameter.
5. If the page list is empty or unavailable, confirm the recovery copy appears
   and the `Quay lại kết nối` button resets the flow.

---

## 4. Visual / UI-UX QA (Manual Pass)

Goal: catch what automated scripts cannot — layout, spacing, contrast,
Vietnamese copy, empty/loading/error states.

### Per-page procedure

1. **Navigate** to the route (desktop 1440×900 first).
2. **Screenshot** annotated (`agent-browser ... screenshot --annotate out.png`).
3. **Visual scan** — use the taxonomy below as a checklist.
4. **Interact** with every primary control; confirm feedback within ~300 ms.
5. **Repeat at 390×844** (iPhone 12 viewport) — assert
   `document.documentElement.scrollWidth <= window.innerWidth + 2` (no horiz overflow).
6. **Check console** — `agent-browser ... console` and `... errors`.

### Visual bug taxonomy (what to file)

- **Layout:** misalignment, overlap, clipped text, z-index stacking, large
  layout shifts on load.
- **Typography:** wrong font/size/weight (project uses the graphite-cloud token
  system — see [`docs/design-tokens-graphite-cloud.md`](../design/design-tokens-graphite-cloud.md));
  Vietnamese diacritics render correctly.
- **Color/contrast:** insufficient contrast (WCAG AA = 4.5:1 for body text).
- **Responsive:** horizontal scroll on mobile, bottom-nav reachability,
  safe-area insets.
- **States:** empty states (helpful, not just "No data"), loading skeletons
  (not just spinners), error states (actionable message).
- **Animation:** jank, stuck transitions, autoplay that traps focus.

### UX bug taxonomy (what to file)

- **Feedback:** actions with no visible result; missing toasts on
  create/update/delete.
- **Dead ends:** no way back; destructive action without confirmation.
- **Inconsistency:** same action labeled differently across pages; different
  empty-state patterns.
- **Keyboard:** can't tab to all controls; focus lost after modal close.
- **i18n:** any English string surfaced to the user (project is
  Vietnamese-first — file under Content if it's a leftover/lorem).
- **Defaults:** unintuitive initial filter/sort; page remembers stale filter.

### Severity scale (use in every report)

| Severity | Meaning |
|----------|---------|
| `critical` | Blocks a core workflow, data loss, or crash |
| `high` | Major feature broken, no workaround |
| `medium` | Works but with noticeable problem, workaround exists |
| `low` | Cosmetic / polish |

---

## 5. Functional / Logic QA (Browser Scripts)

Automated scripts catch regressions a human will miss on the 20th run. The
project already ships [`frontend/qa/*.cjs`](../frontend/qa/) Playwright
scripts — extend that pattern.

### 5.1 Run the existing probes first

```bash
mkdir -p /tmp/qa-audit
cd frontend
node qa/qa-smoke.cjs     # anonymous load + console/network error capture
node qa/qa-audit.cjs     # full route sweep (desktop + mobile) with screenshots
```

Outputs land in `/tmp/qa-audit/`. Read the console — every `pageerror` and
`>=400` response is a candidate bug.

### 5.2 Authenticated smoke (template)

`qa-smoke.cjs` and `qa-audit.cjs` currently hardcode a **stale prod credential**
(`admin@tingting.vip`). When you write or edit these, use the dev account from
§2. Minimal authenticated smoke:

```js
// frontend/qa/qa-auth-smoke.cjs
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  await page.fill('input[name="email"]', 'admin@vfic.dev');
  await page.fill('input[name="password"]', 'admin123');
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => {}),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForTimeout(2500);

  console.log('Post-login URL:', page.url());         // expect http://localhost:5173/#/
  console.log('Has token:', !!(await page.evaluate(
    () => localStorage.getItem('RaStore.auth.access_token'))));
  console.log('Errors:', errors);
  await page.screenshot({ path: '/tmp/qa-audit/auth-smoke.png', fullPage: true });
  await browser.close();
})();
```

### 5.3 Route health sweep (the core regression check)

For each route in §3, assert: (a) renders without `pageerror`, (b) no `>=400`
network response, (c) `main#main-content` landmark present, (d) no horizontal
overflow. `qa-audit.cjs` already does the screenshot + error capture — wrap it
with assertions when adding a CI gate.

### 5.4 CRUD safety tests (per resource)

For `projects`, `users`, `personas` — exercise the full
create→edit→delete cycle on a `QA-*` record:

1. Submit the create form **empty** → verify validation rejects it.
2. Create `QA-<resource>-<timestamp>`.
3. Verify it appears in the list.
4. Edit one field → verify list/detail refresh.
5. Open the delete dialog → **verify it names the target** before confirming.
6. Delete → reload → verify count returns to baseline.

### 5.5 Domain-logic checks specific to this app

These are the logic bugs most likely to regress — cover them every run:

- **Conversation mode menu** (`#/conversations/:id`): switching Human ↔
  Semi-auto ↔ Chatbot persists across reload; in Chatbot mode the composer is
  **disabled**; takeover toggles a realtime presence event.
- **Leads ↔ Conversations deep-link**: from a lead detail modal,
  `Mở cuộc trò chuyện` opens the matching conversation; back returns to the
  filtered leads list (not a blank state).
- **Dashboard attention section**: surfaces failed knowledge sources and
  attention items; clicking a shortcut lands on the right detail. Toggle with
  `VITE_ATTENTION_DASHBOARD_ENABLED`.
- **Role gating**: log in as `lan.nguyen@vfic.dev` (recruiter); confirm
  `#/hieu-suat` and `#/users` redirect / hide. Log in as `admin@vfic.dev`;
  confirm both are reachable.
- **Token refresh**: after login, manually expire the access token in
  `localStorage` (`RaStore.auth.access_token = "bad"`) and trigger an API
  call — the refresh flow should silently recover (`POST /api/v1/auth/refresh`)
  without logging the user out.
- **Socket.IO realtime**: with two browser sessions (admin + recruiter),
  sending in one should update the conversation list in the other within ~1 s.

### 5.6 Console / network errors — always capture

Every script should attach these listeners (copy from `qa-audit.cjs`):

```js
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push(e.message));
page.on('response', r => { if (r.status() >= 400) netErrors.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
```

File findings for any unhandled exception, any `4xx`/`5xx` that isn't an
intentional auth check, and any CORS / mixed-content warning.

---

## 6. Latency / Performance QA

The production target is a **2 vCPU droplet** with a sub-second fast-lane bot
reply budget (see the archived
[latency plan](../archive/chatbot-latency-improvement-plan.md)). Dev hardware is
faster, so treat dev numbers as a **lower bound** — if it's slow in dev it will
be worse in prod.

### 6.1 Page-load + route-transition timing (scripted)

```js
// Latency probe — drop into a qa-perf.cjs
const t0 = Date.now();
await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
console.log('Initial load (networkidle):', Date.now() - t0, 'ms');

for (const route of ['/', '/conversations', '/projects', '/users']) {
  const t = Date.now();
  await page.goto(`http://localhost:5173/#${route}`, { waitUntil: 'networkidle' });
  console.log(`Route ${route}:`, Date.now() - t, 'ms');
}
```

Flag any route transition **> 1500 ms** in dev (maps to perceived jank on the
2 vCPU box). Use `waitUntil: 'domcontentloaded'` in addition to
`networkidle` to separate "paint" from "fully settled".

### 6.2 Backend API latency (curl, per endpoint)

```bash
# Authenticated request — replace <TOKEN> from a login call
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@vfic.dev","password":"admin123"}' | jq -r .access_token)

for ep in /api/v1/auth/me /api/v1/conversations /api/v1/leads /api/v1/dashboard /api/v1/performance; do
  printf "%-32s " "$ep"
  curl -s -o /dev/null -w "%{http_code}  %{time_total}s\n" \
    -H "Authorization: Bearer $TOKEN" http://localhost:8000$ep
done
```

Flag any `GET` API endpoint **> 300 ms** p50 in dev. These are the same
endpoints the dashboard polls, so a slow one cascades into perceived UI lag.

### 6.3 Bundle / network weight (Vite build)

```bash
cd frontend && npm run build:analyze    # ANALYZE=true → rollup output
```

Confirm the manual chunk strategy (react-vendor, ra-vendor, tanstack-vendor,
lucide-vendor, router-vendor, realtime-vendor, forms-vendor, virtua-vendor)
is intact — a vendor chunk that has ballooned usually means a new dependency
slipped into the wrong chunk.

### 6.4 Long-list virtualization

`conversations` and `bot_runs` are virtualized with `virtua` (`VList` — see
`ChatThread.tsx`). Verify in dev by loading the list and checking the
DOM node count stays roughly constant while scrolling — if thousands of row
nodes mount, virtualization is broken.

### 6.5 Realtime echo latency

With two sessions open, send a message; measure wall-clock time to the other
session's conversation list updating. **Budget: < 1000 ms.** If it lags,
suspect the Redis pub/sub bridge or Socket.IO room join, not the UI.

### 6.6 RAG / bot turn latency (when exercising the bot)

`/api/v1/performance` exposes LLM call percentiles
(`percentile_cont` over `llm_call_ms`). Hit it after generating bot traffic
through the Zalo mock and confirm fast-lane turns (greetings/FAQ) are
sub-second. Slow turns here are a backend concern, not a frontend one.

---

## 7. Recording Findings

### Output layout (per QA run)

```
plans/qa-<YYYY-MM-DD>/
├── report.md          ← findings table + severity + repro
├── screenshots/       ← annotated PNG per page/issue
├── videos/            ← .webm repros for interactive bugs (optional)
└── console-captures/  ← raw script stdout
```

For agent-browser-driven sessions, follow the
[`ck:agent-browser` dogfood skill](https://github.com/vercel-labs/agent-browser):
static issues (typos, layout) get a single annotated screenshot; interactive
bugs get a step-by-step repro with a video and per-step screenshots.

### Finding entry format (copy into `report.md`)

```markdown
### ISSUE-001 — <short title>
- **Severity:** medium
- **Category:** Visual | Functional | UX | Content | Performance | Console | A11y
- **Route:** #/conversations
- **Repro:**
  1. Login as admin@vfic.dev — screenshot: screenshots/issue-001-step-1.png
  2. Open conversation #42 — screenshot: screenshots/issue-001-step-2.png
  3. Switch mode to Chatbot — composer stays enabled (bug)
     screenshot: screenshots/issue-001-result.png ; video: videos/issue-001-repro.webm
- **Expected:** composer disabled in Chatbot mode
- **Actual:** composer remains editable
- **Console:** (any pageerror / 4xx captured)
```

### Exit checklist (before closing the session)

- [ ] All `QA-*` records deleted (projects, users, personas, knowledge sources)
- [ ] Any real record mutated during the run restored to its original value
- [ ] No test messages left in real candidate conversations
- [ ] `report.md` summary counts match the issue blocks
- [ ] Screenshots/videos referenced in repro steps actually exist
- [ ] Console-capture files saved for the route sweep
- [ ] Session closed: `agent-browser --session <name> close`

---

## 8. When to Escalate (Don't Auto-Fix During QA)

QA's job is to **find and document**, not patch mid-run. Escalate to a code
change (separate task) when a finding touches a protected area — auth/JWT/CORS/HMAC,
DB migrations, or candidate-facing bot behavior:

- **Auth / JWT / CORS / HMAC** — don't tweak; describe and hand off.
- **Bot pipeline / safety / grounding / prompts** — any candidate-facing
  behavior change needs explicit approval.
- **DB migrations** — never write one to "fix" data you mutated during QA;
  restore manually instead.
- **`docker-compose.yml`, `Caddyfile`, `Makefile` deploy targets** — production
  surface; describe, don't edit.

If a finding is purely cosmetic (a typo, a padding value) and lives in
`atomic-crm/` product code, a follow-up code task is fine — but keep QA and
fix as separate steps so the repro evidence stays clean.

---

## 9. Quick-Start Checklist (TL;DR for the next agent)

```bash
# 1. Stack up
make dev
curl -s http://localhost:8000/health            # → ok
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173/   # → 200

# 2. Anonymous + authenticated smoke
mkdir -p /tmp/qa-audit
cd frontend && node qa/qa-smoke.cjs              # fix stale creds first (§5.2)

# 3. Visual sweep — every route in §3, desktop + 390x844
agent-browser --session qa open http://localhost:5173/
# ... login as admin@vfic.dev / admin123, screenshot each route

# 4. Functional sweep — CRUD on QA-* records + domain-logic checks in §5.5

# 5. Perf sweep — §6.1 (route timing) + §6.2 (API latency)

# 6. Write findings → plans/qa-<date>/report.md using the ISSUE template (§7)

# 7. Exit checklist (§7) — cleanup QA-* records, close session
```

**Remember:** prefix temp records with `QA-`, never touch seed/business data,
never message real candidates, and restore anything you mutate.
