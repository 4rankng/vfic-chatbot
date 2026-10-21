/**
 * QA evidence: mobile surfaces lane 2 (2026-10-21) at 390×844.
 *
 * Serves the frontend with Vite, opens the REAL app (auth seeded, every
 * /api/v1 call answered from fixtures via Playwright routes), and writes
 * viewport PNGs into ../../qa/<run>/:
 *
 *   before/after-inbox-list.png     conversation list (master pane)
 *   before/after-inbox-thread.png   tapped drill-down + composer
 *   before/after-dashboard.png      dashboard first viewport (KPI cards)
 *   before/after-leads.png          leads list (card list / rows)
 *
 *   node qa/mobile-surfaces-shots.cjs <before|after> <outdir>
 */
const path = require("node:path");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const FRONTEND = path.resolve(__dirname, "..");
const PORT = 5198;
const TAG = process.argv[2];
const OUTDIR = process.argv[3];

const b64url = (value) =>
  Buffer.from(JSON.stringify(value)).toString("base64url");
const FAKE_JWT = `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url({
  sub: "1",
  exp: 4102444800,
})}.qa-signature`;

const now = new Date("2026-10-21T10:00:00+07:00");
const iso = (daysAgo, hour = 9) => {
  const d = new Date(now);
  d.setDate(d.getDate() - daysAgo);
  d.setHours(hour, 12, 0, 0);
  return d.toISOString();
};

const LEADS = [
  // Cohort "kỳ này" (created within the last 7 days).
  {
    id: 41,
    zalo_id: "z-41",
    contact_id: null,
    name: "Nguyễn Thị Mai",
    phone: "0912345678",
    desired_job: "Nhân viên kinh doanh",
    expected_salary: "12–15 triệu",
    lead_score: "hot",
    lead_stage: "CONTACTING",
    created_at: iso(1),
    updated_at: iso(1),
    notes: null,
  },
  {
    id: 42,
    zalo_id: "z-42",
    contact_id: null,
    name: "Trần Văn Hùng",
    phone: "0987654321",
    desired_job: "Kỹ sư vận hành",
    expected_salary: "18 triệu",
    lead_score: "warm",
    lead_stage: "NEW",
    created_at: iso(2),
    updated_at: iso(2),
    notes: null,
  },
  {
    id: 43,
    zalo_id: "z-43",
    contact_id: null,
    name: "Lê Thị Hoa",
    phone: "0903456789",
    desired_job: "Chăm sóc khách hàng",
    expected_salary: "10 triệu",
    lead_score: null,
    lead_stage: "REGISTERED",
    created_at: iso(4),
    updated_at: iso(1),
    notes: null,
  },
  {
    id: 44,
    zalo_id: "z-44",
    contact_id: null,
    name: "Phạm Quốc Anh",
    phone: "0978123456",
    desired_job: "Trưởng ca sản xuất",
    expected_salary: "20 triệu",
    lead_score: "warm",
    lead_stage: "NEW",
    created_at: iso(6),
    updated_at: iso(6),
    notes: null,
  },
  {
    id: 45,
    zalo_id: "z-45",
    contact_id: null,
    name: "Hoàng Thị Lan",
    phone: "0934567890",
    desired_job: "Nhân viên kho",
    expected_salary: "9 triệu",
    lead_score: null,
    lead_stage: "REGISTERED",
    created_at: iso(7),
    updated_at: iso(3),
    notes: null,
  },
  // Cohort "kỳ trước" (8–14 days ago).
  {
    id: 31,
    zalo_id: "z-31",
    contact_id: null,
    name: "Vũ Minh Tuấn",
    phone: "0945678901",
    desired_job: "Nhân viên kinh doanh",
    expected_salary: "14 triệu",
    lead_score: "hot",
    lead_stage: "REGISTERED",
    created_at: iso(9),
    updated_at: iso(8),
    notes: null,
  },
  {
    id: 32,
    zalo_id: "z-32",
    contact_id: null,
    name: "Đặng Thị Hồng",
    phone: "0956789012",
    desired_job: "Kế toán tổng hợp",
    expected_salary: "15 triệu",
    lead_score: "warm",
    lead_stage: "CONTACTING",
    created_at: iso(10),
    updated_at: iso(9),
    notes: null,
  },
  {
    id: 33,
    zalo_id: "z-33",
    contact_id: null,
    name: "Bùi Văn Nam",
    phone: "0967890123",
    desired_job: "Kỹ sư bảo trì",
    expected_salary: "22 triệu",
    lead_score: null,
    lead_stage: "SKIPPED",
    created_at: iso(12),
    updated_at: iso(11),
    notes: null,
  },
  {
    id: 34,
    zalo_id: "z-34",
    contact_id: null,
    name: "Ngô Thanh Tùng",
    phone: "0898901234",
    desired_job: "Nhân viên kho",
    expected_salary: "10 triệu",
    lead_score: "warm",
    lead_stage: "REGISTERED",
    created_at: iso(14),
    updated_at: iso(10),
    notes: null,
  },
  // Older history (coverage tail).
  {
    id: 21,
    zalo_id: "z-21",
    contact_id: null,
    name: "Đỗ Thị Hạnh",
    phone: "0889012345",
    desired_job: "Chăm sóc khách hàng",
    expected_salary: "11 triệu",
    lead_score: "not_interested",
    lead_stage: "SKIPPED",
    created_at: iso(21),
    updated_at: iso(20),
    notes: null,
  },
];

const CONVERSATIONS = [
  {
    id: "c-41",
    zalo_chat_id: "z-41",
    zalo_channel: "bot",
    mode: "bot",
    version: 3,
    needs_human: true,
    last_inbound_at: iso(0, 9),
    last_outbound_at: iso(0, 8),
    assigned_recruiter_id: null,
    created_at: iso(1),
    updated_at: iso(0, 9),
    unread_count: 2,
    contact_id: null,
    channel_identity: {
      id: "ci-1",
      provider: "zalo_oa",
      account_key: "tingting",
      external_id: "oa-1",
      display_channel: "zalo_oa",
    },
  },
  {
    id: "c-42",
    zalo_chat_id: "z-42",
    zalo_channel: "bot",
    mode: "human",
    version: 5,
    needs_human: false,
    last_inbound_at: iso(1, 15),
    last_outbound_at: iso(1, 16),
    assigned_recruiter_id: "1",
    created_at: iso(2),
    updated_at: iso(1, 16),
    unread_count: 0,
    contact_id: null,
    channel_identity: {
      id: "ci-1",
      provider: "zalo_oa",
      account_key: "tingting",
      external_id: "oa-1",
      display_channel: "zalo_oa",
    },
  },
  {
    id: "c-43",
    zalo_chat_id: "z-43",
    zalo_channel: "bot",
    mode: "bot",
    version: 2,
    needs_human: false,
    last_inbound_at: iso(3, 11),
    last_outbound_at: iso(3, 11),
    assigned_recruiter_id: null,
    created_at: iso(4),
    updated_at: iso(3, 11),
    unread_count: 1,
    contact_id: null,
    channel_identity: {
      id: "ci-1",
      provider: "zalo_oa",
      account_key: "tingting",
      external_id: "oa-1",
      display_channel: "zalo_oa",
    },
  },
];

// MessageOut shape: `body` + `sender` (CANDIDATE/BOT/RECRUITER/SYSTEM) —
// chat-repository.ts `toMessage` maps these to the CRM's message rows.
const MESSAGES = {
  "c-41": [
    {
      id: "m-1",
      zalo_message_id: "zmsg-1",
      conversation_id: "c-41",
      sender: "CANDIDATE",
      body: "Cho em hỏi vị trí nhân viên kinh doanh còn tuyển không ạ?",
      delivery_status: "sent",
      recruiter_id: null,
      created_at: iso(1, 8),
    },
    {
      id: "m-2",
      zalo_message_id: "zmsg-2",
      conversation_id: "c-41",
      sender: "BOT",
      body: "Dạ bên em vẫn đang tuyển ạ. Em cho anh/chị xin số điện thoại để tư vấn kỹ hơn nhé.",
      delivery_status: "sent",
      recruiter_id: null,
      created_at: iso(1, 9),
    },
    {
      id: "m-3",
      zalo_message_id: "zmsg-3",
      conversation_id: "c-41",
      sender: "CANDIDATE",
      body: "Số của em là 0912345678 ạ.",
      delivery_status: "sent",
      recruiter_id: null,
      created_at: iso(0, 9),
    },
    {
      id: "m-4",
      zalo_message_id: "zmsg-4",
      conversation_id: "c-41",
      sender: "SYSTEM",
      body: "Đã chuyển sang chế độ bot",
      delivery_status: "sent",
      recruiter_id: null,
      created_at: iso(0, 9),
    },
    {
      id: "m-5",
      zalo_message_id: "zmsg-5",
      conversation_id: "c-41",
      sender: "RECRUITER",
      body: "Cảm ơn em! Bên anh sẽ liên hệ trong hôm nay nhé.",
      delivery_status: "sent",
      recruiter_id: "1",
      created_at: iso(0, 10),
    },
  ],
  "c-42": [
    {
      id: "m-6",
      zalo_message_id: "zmsg-6",
      conversation_id: "c-42",
      sender: "CANDIDATE",
      body: "Em muốn ứng tuyển kỹ sư vận hành ạ.",
      delivery_status: "sent",
      recruiter_id: null,
      created_at: iso(1, 15),
    },
    {
      id: "m-7",
      zalo_message_id: "zmsg-7",
      conversation_id: "c-42",
      sender: "RECRUITER",
      body: "Em có kinh nghiệm mấy năm rồi ạ?",
      delivery_status: "sent",
      recruiter_id: "1",
      created_at: iso(1, 16),
    },
  ],
  "c-43": [
    {
      id: "m-8",
      zalo_message_id: "zmsg-8",
      conversation_id: "c-43",
      sender: "CANDIDATE",
      body: "Chị cho em hỏi lương của vị trí chăm sóc khách hàng ạ.",
      delivery_status: "sent",
      recruiter_id: null,
      created_at: iso(3, 11),
    },
  ],
};

const ATTENTION = {
  updated_at: iso(0, 10),
  counters: {
    needs_reply: 4,
    overdue: 2,
    due_today: 3,
    priority: 5,
    unread: 3,
  },
  immediate: [
    {
      key: "c-41",
      reason: "REPLY_OVERDUE",
      urgency_at: iso(0, 9),
      conversation_id: "c-41",
      lead_id: 41,
      name: "Nguyễn Thị Mai",
      phone: "0912345678",
      desired_job: "Nhân viên kinh doanh",
      lead_stage: "CONTACTING",
      lead_score: "hot",
      last_inbound_at: iso(0, 9),
      due_at: null,
      delivery_status: null,
      action: "OPEN_CONVERSATION",
    },
    {
      key: "c-43",
      reason: "HUMAN_ESCALATION",
      urgency_at: iso(3, 11),
      conversation_id: "c-43",
      lead_id: 43,
      name: "Lê Thị Hoa",
      phone: "0903456789",
      desired_job: "Chăm sóc khách hàng",
      lead_stage: "REGISTERED",
      lead_score: null,
      last_inbound_at: iso(3, 11),
      due_at: null,
      delivery_status: null,
      action: "OPEN_CONVERSATION",
    },
  ],
  today: [],
};

const METRICS = {
  open_conversations: 7,
  hot_leads: 3,
  pending_followups: 2,
  bot_suppression_rate: 0,
  failed_zalo_sends: 0,
  bot_errors: 0,
  bot_run_count: 24,
  bot_sent_count: 21,
  bot_suppressed_count: 3,
  bot_success_rate: 87.5,
  avg_bot_response_seconds: 2.4,
  webhook_queue_depth: 0,
  active_turns: 1,
  p95_bot_response_seconds: 4.1,
  turns_last_5min: 2,
  total_leads: 84,
  qualified_count: 0,
  hired_count: 21,
  hired_rate: 25,
  unread_conversation_count: 2,
  stage_breakdown: [
    { value: "NEW", count: 34, percentage: 40 },
    { value: "CONTACTING", count: 29, percentage: 35 },
    { value: "REGISTERED", count: 21, percentage: 25 },
    { value: "SKIPPED", count: 0, percentage: 0 },
  ],
  knowledge_ingest: null,
};

const conversationSummary = (id) => {
  const found = CONVERSATIONS.find((c) => c.id === id || c.zalo_chat_id === id);
  return found ?? CONVERSATIONS[0];
};

async function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await globalThis.fetch(url);
      if (response.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`vite did not start at ${url}`);
}

const json = (route, body) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });

async function main() {
  if (!TAG || !OUTDIR)
    throw new Error("usage: node mobile-surfaces-shots.cjs <tag> <outdir>");

  const vite = spawn(
    "npx",
    ["vite", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"],
    { cwd: FRONTEND, stdio: ["ignore", "pipe", "pipe"] },
  );
  vite.stderr.on("data", (chunk) => process.stderr.write(chunk));

  const browser = await chromium.launch({ headless: true });
  try {
    await waitForServer(`http://127.0.0.1:${PORT}/`, 60_000);
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
      locale: "vi-VN",
      timezoneId: "Asia/Ho_Chi_Minh",
    });
    await context.addInitScript(
      ([accessKey, refreshKey, token]) => {
        window.localStorage.setItem(accessKey, token);
        window.localStorage.setItem(refreshKey, token);
      },
      ["RaStore.auth.access_token", "RaStore.auth.refresh_token", FAKE_JWT],
    );
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error")
        console.error(`[console] ${message.text()}`);
    });
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      const p = url.pathname;
      if (p.endsWith("/auth/me") || p.endsWith("/auth/refresh")) {
        return json(route, {
          id: "1",
          email: "admin@example.org",
          full_name: "QA Admin",
          role: "admin",
          access_token: FAKE_JWT,
          refresh_token: FAKE_JWT,
        });
      }
      if (p.endsWith("/installation/runtime")) {
        return json(route, {
          generation: 1,
          resources: [],
          routes: [],
          navigation: [],
        });
      }
      if (p.endsWith("/dashboard/attention")) return json(route, ATTENTION);
      if (p.endsWith("/dashboard/metrics")) return json(route, METRICS);
      if (p.endsWith("/leads")) {
        const zaloId = url.searchParams.get("zalo_id");
        const zaloIds = url.searchParams.get("zalo_ids");
        const contactId = url.searchParams.get("contact_id");
        let rows = LEADS;
        if (zaloId) rows = LEADS.filter((lead) => lead.zalo_id === zaloId);
        else if (zaloIds)
          rows = LEADS.filter((lead) =>
            zaloIds.split(",").includes(lead.zalo_id),
          );
        else if (contactId)
          rows = LEADS.filter((lead) => lead.contact_id === contactId);
        return json(route, { data: rows, total: rows.length });
      }
      if (p.endsWith("/conversations/by-zalo-ids")) {
        const ids = (url.searchParams.get("ids") ?? "").split(",").filter(Boolean);
        const rows = CONVERSATIONS.filter((c) => ids.includes(c.zalo_chat_id));
        return json(route, { data: rows, total: rows.length });
      }
      if (p.endsWith("/conversations/by-contact-ids")) {
        return json(route, { data: [], total: 0 });
      }
      if (p.endsWith("/last-messages/batch")) {
        const ids = (url.searchParams.get("ids") ?? "").split(",").filter(Boolean);
        const snippets = {};
        for (const id of ids) {
          const rows = MESSAGES[id] ?? [];
          snippets[id] = rows[rows.length - 1]?.body ?? "";
        }
        return json(route, { snippets });
      }
      const messagesMatch = p.match(/\/conversations\/([^/]+)\/messages$/);
      if (messagesMatch) {
        const rows = MESSAGES[messagesMatch[1]] ?? [];
        return json(route, { data: rows, total: rows.length });
      }
      const conversationMatch = p.match(/\/conversations\/([^/]+)$/);
      if (conversationMatch) {
        return json(route, conversationSummary(conversationMatch[1]));
      }
      if (p.endsWith("/conversations")) {
        return json(route, {
          data: CONVERSATIONS,
          total: CONVERSATIONS.length,
        });
      }
      return json(route, { data: [], total: 0 });
    });

    const shot = (name) =>
      page.screenshot({ path: path.join(OUTDIR, `${TAG}-${name}.png`) });

    // 1) Inbox master list.
    await page.goto(`http://127.0.0.1:${PORT}/#/conversations`);
    await page.locator(".left-panel .conversation").first().waitFor({
      timeout: 20_000,
    });
    await page.waitForTimeout(700);
    await shot("inbox-list");

    // 2) Tap → drill-down thread + composer.
    await page.locator(".left-panel .conversation").first().click();
    await page.locator(".composer-wrap").waitFor({ timeout: 20_000 });
    await page.waitForTimeout(800);
    await shot("inbox-thread");

    // 2b) Context panel from the header info trigger → bottom sheet.
    await page.locator(".conversation-header-identity-button").click();
    await page.locator(".candidate-context-sheet").waitFor({ timeout: 20_000 });
    await page.waitForTimeout(500);
    await shot("inbox-context");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);

    // 3) Dashboard first viewport.
    await page.goto(`http://127.0.0.1:${PORT}/#/`);
    await page
      .getByRole("heading", { name: "Tổng quan" })
      .waitFor({ timeout: 20_000 });
    await page.waitForTimeout(900);
    await shot("dashboard");

    // 4) Leads surface (card list on mobile).
    const leadsHeading = page.getByRole("heading", {
      name: "Ứng viên mới",
      exact: true,
    });
    await leadsHeading.waitFor({ timeout: 20_000 });
    await leadsHeading.evaluate((el) =>
      el.scrollIntoView({ block: "start", behavior: "instant" }),
    );
    await page.waitForTimeout(600);
    await shot("leads");

    await context.close();
  } finally {
    await browser.close();
    vite.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
