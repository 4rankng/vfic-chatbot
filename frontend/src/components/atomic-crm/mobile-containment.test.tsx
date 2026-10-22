/**
 * Phone containment contracts (320×568 and 390×844) for the surfaces the
 * mobile overhaul touched: nothing scrolls sideways at the document level and
 * no visible control or text block spills past its surface. Each surface
 * mounts the real component with the same mock seams its own suite uses.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as RaCoreModule from "ra-core";

import "@/index.css";
import "@/flat-surfaces.css";
// The containment contract is CSS-geometry: every sheet that styles the
// surfaces under test must be loaded, exactly as each surface's own suite does.
import "./conversations/inbox.css";
import "./projects/projects.css";
import "./users/users.css";
import "./integrations/settings.css";
import "./dashboard/dashboard.css";
import "./performance/performance.css";
import { testI18nProvider } from "./providers/commons/i18nProvider";
import { TestMessages } from "./providers/commons/TestMessages";
import { expectContained } from "@/test/mobile-containment";

// --- shared mutable seams ------------------------------------------------

const viewport = vi.hoisted(() => ({ isMobile: true }));

const listState = vi.hoisted(() => ({
  value: {
    data: [] as unknown[],
    isPending: false,
    error: null as Error | null,
    total: 0,
    page: 1,
    perPage: 25,
    setPage: (_page: number) => {},
    filterValues: {} as Record<string, unknown>,
    displayedFilters: {} as Record<string, unknown>,
    setFilters: () => {},
    setPerPage: () => {},
    hasNextPage: false,
    hasPreviousPage: false,
  },
}));

const chatState = vi.hoisted(() => ({
  messages: [] as Array<Record<string, unknown>>,
}));

const perfState = vi.hoisted(() => ({
  value: {
    data: {
      window: "7d",
      response_time: {
        p50_ms: 1500,
        p95_ms: 3200,
        trend: [
          {
            bucket: "2026-07-12T08:00:00+07:00",
            p50_ms: 1500,
            p95_ms: 3200,
            turns: 12,
          },
        ],
      },
      conversion: { rate_pct: 25.0, with_phone: 3, candidate_chats: 12 },
    },
    isPending: false,
    isFetching: false,
    isError: false,
    refetch: () => Promise.resolve(),
    dataUpdatedAt: 1_784_732_616_000,
  },
}));

const apiJson = vi.hoisted(() => vi.fn());

// --- module mocks ---------------------------------------------------------

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => viewport.isMobile,
  useIsWideDesktop: () => false,
  useIsNarrow: () => viewport.isMobile,
}));

vi.mock("ra-core", async (importOriginal) => ({
  ...(await importOriginal<typeof RaCoreModule>()),
  useTranslate: () => testI18nProvider.translate,
  useNotify: () => vi.fn(),
  usePermissions: () => ({ permissions: "admin", isPending: false }),
  useGetList: () => ({ data: [], total: 0 }),
  useGetIdentity: () => ({ identity: { id: "recruiter-1" } }),
  useDataProvider: () => ({
    update: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
    getList: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
    getOne: vi.fn(() => Promise.resolve({ data: {} })),
    markAsRead: vi.fn(() => Promise.resolve()),
    sendHumanReply: vi.fn(() => Promise.resolve()),
    retryHumanReply: vi.fn(() => Promise.resolve()),
    enableUser: vi.fn(),
    disableUser: vi.fn(),
    resetUserPassword: vi.fn(),
  }),
  useListContext: () => listState.value,
  useListPaginationContext: () => listState.value,
  useInfinitePaginationContext: () => ({
    fetchNextPage: () => Promise.resolve(),
    hasNextPage: false,
    isFetchingNextPage: false,
  }),
  useGetOne: () => ({ data: undefined, isPending: false, isError: false }),
  useDeleteWithUndoController: () => ({
    isPending: false,
    handleDelete: () => {},
  }),
  useCreatePath: () => (options: { resource: string; type: string }) =>
    `/${options.resource}/${options.type}`,
  // Real `ListBase` provisions its own empty list context, shadowing the
  // seam these suites drive; the surfaces under test read the context only.
  ListBase: ({ children }: { children?: ReactNode }) => <>{children}</>,
  InfiniteListBase: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock(
  "./conversations/useConversationCapabilitySlots",
  async (importOriginal) => ({
    ...(await importOriginal<Record<string, unknown>>()),
    useConversationCapabilitySlots: () => ({}),
  }),
);

vi.mock("virtua", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  VList: ({
    children,
    className,
    style,
    onScroll,
  }: {
    children?: ReactNode;
    className?: string;
    style?: Record<string, unknown>;
    onScroll?: (offset: number) => void;
  }) => (
    <div
      className={className}
      style={{ height: "100%", overflowY: "auto", ...style }}
      onScroll={(e) => onScroll?.((e.currentTarget as HTMLElement).scrollTop)}
    >
      <div>{children}</div>
    </div>
  ),
}));

vi.mock("./conversations/application/conversation-runtime", () => ({
  loadConversationSnippets: () => Promise.resolve({}),
}));

vi.mock("./conversations/ChannelAdapterSelector", () => ({
  ChannelAdapterSelector: () => <div />,
}));

vi.mock("./conversations/presentation/conversation-message-state", () => ({
  useConversationMessages: () => chatState.messages,
  useConversationFlags: () => ({
    isLoading: false,
    isLoadingMore: false,
    hasMore: false,
    initialError: null,
    historyError: null,
  }),
}));

vi.mock("./conversations/presentation/use-conversation-realtime", () => ({
  useConversationRealtime: () => ({}),
}));

vi.mock("./conversations/presentation/use-conversation-actions", () => ({
  useConversationActions: () => ({
    effectiveMode: "human",
    isBotMode: false,
    needsClaim: false,
    canHumanReply: true,
    setConversationMode: () => {},
    handleTakeover: () => Promise.resolve(),
    isChangingMode: false,
  }),
}));

vi.mock("./performance/usePerformanceStats", () => ({
  usePerformanceStats: () => perfState.value,
}));

vi.mock("@/lib/apiClient", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  apiJson,
}));

vi.mock("./projects/ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: ({ project }: { project: { name: string } }) => (
    <p>Kiến thức dự án {project.name}</p>
  ),
}));

// Settings pulls every integration gateway; the containment contract does not
// exercise them, but the groups page renders their status lines, so the loaders
// return the same shapes the navigation suite mounts with (arrays included —
// the LLM failover line joins its order list).
const gatewayLoaders = vi.hoisted(() => ({
  loadZaloSettings: vi.fn(() =>
    Promise.resolve({
      zalo_bot_token: { configured: true, preview: "dev-…oken" },
      zalo_bot_webhook_secret: { configured: false },
      zalo_oa_app_id: { configured: false, value: "" },
      zalo_oa_secret_key: { configured: false },
      zalo_oa_access_token: { configured: false },
      zalo_oa_refresh_token: { configured: false },
      zalo_bot_api_base: "",
      zalo_oa_api_base: "",
      zalo_oa_webhook_signature: {
        last_status: "mismatched",
        last_ts: 1_784_732_616,
        last_mismatch_ts: 1_784_732_616,
        consec_failures: 526,
      },
    }),
  ),
  loadMinimaxSettings: vi.fn(() =>
    Promise.resolve({
      minimax_api_key: { configured: false },
      minimax_base_url: "",
      minimax_agent_model: "minimax-model",
      minimax_extractor_model: "minimax-model",
      minimax_enable: true,
      llm_default_provider: "minimax" as const,
      llm_failover_order: ["minimax", "openrouter", "custom"],
    }),
  ),
  loadOpenRouterSettings: vi.fn(() =>
    Promise.resolve({
      openrouter_api_key: { configured: false },
      openrouter_base_url: "",
      openrouter_agent_model: "deepseek/deepseek-v4-flash",
      openrouter_extractor_model: "deepseek/deepseek-v4-flash",
      openrouter_digest_model: "deepseek/deepseek-v4-flash",
      openrouter_enable: false,
      llm_default_provider: "minimax" as const,
      llm_failover_order: ["minimax", "openrouter", "custom"],
    }),
  ),
  loadCustomLlmSettings: vi.fn(() =>
    Promise.resolve({
      custom_llm_api_key: { configured: false },
      custom_llm_base_url: "",
      custom_llm_agent_model: "",
      custom_llm_fast_model: "",
      custom_llm_label: "Dự phòng",
      custom_llm_enable: false,
      custom_llm_usable: false,
      llm_default_provider: "minimax" as const,
      llm_failover_order: ["minimax", "openrouter", "custom"],
    }),
  ),
  loadJevSettings: vi.fn(() =>
    Promise.resolve({
      jev_api_key: { configured: false },
      jev_model: "",
      jev_enable: false,
      jev_usable: false,
    }),
  ),
  loadCloudfoneSettings: vi.fn(() => Promise.resolve({ enabled: false })),
  loadEmailDigestSettings: vi.fn(() =>
    Promise.resolve({
      enabled: false,
      frequency: "daily" as const,
      send_time: "09:00",
      recipients: [] as string[],
    }),
  ),
  listCloudfoneTranscripts: vi.fn(() =>
    Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 }),
  ),
  loadFacebookStatus: vi.fn(() =>
    Promise.resolve({ enabled: false, accounts: [] }),
  ),
  loadFacebookOAuthPages: vi.fn(() =>
    Promise.resolve({ pages: [], active_page_id: null }),
  ),
}));

vi.mock("./integrations/api", () => ({
  zaloIntegrationGateway: {
    ...gatewayLoaders,
    saveZaloSettings: vi.fn(),
    saveMinimaxSettings: vi.fn(),
    saveOpenRouterSettings: vi.fn(),
    saveCustomLlmSettings: vi.fn(),
    saveJevSettings: vi.fn(),
    saveTingtingSettings: vi.fn(),
    saveCloudfoneSettings: vi.fn(),
    saveEmailDigestSettings: vi.fn(),
    backfillCloudfoneTranscripts: vi.fn(),
    loadTingtingSettings: vi.fn(() =>
      Promise.resolve({
        api_key: { configured: false, preview: null },
        configured: false,
        base_url: "https://api.tingting.vn",
        auth_header: "X-API-Key",
        reset_oa_id: "",
        oa_linked: false,
        oa_id: "",
        oa_name: "",
        oa_label: "",
        oa_verified_at: null,
        oa_last_checked_at: null,
        oa_last_error: "",
        oa_token_updated_at: null,
        oa_token_managed_note: "",
      }),
    ),
    testBotConnection: vi.fn(),
    testOaConnection: vi.fn(() =>
      Promise.resolve({
        configured: false,
        connected: false,
        missing: [],
        errors: [],
        oa_secret_valid: null,
        oa_refresh_ok: null,
        oa_token_expired: false,
      }),
    ),
    testMinimaxConnection: vi.fn(),
    testOpenRouterConnection: vi.fn(),
    testCustomLlmConnection: vi.fn(),
    testJevConnection: vi.fn(),
  },
  facebookIntegrationGateway: {
    loadStatus: gatewayLoaders.loadFacebookStatus,
    loadCredentials: vi.fn(() =>
      Promise.resolve({
        facebook_app_id: { configured: false, value: null },
        facebook_app_secret: { configured: false, preview: null },
        facebook_login_config_id: { configured: false, value: null },
        facebook_webhook_verify_token: { configured: false, preview: null },
      }),
    ),
    saveCredentials: vi.fn(),
    loadOAuthPages: gatewayLoaders.loadFacebookOAuthPages,
    startOAuth: vi.fn(),
    completeOAuth: vi.fn(),
    testConnection: vi.fn(),
    disconnect: vi.fn(),
  },
}));

import { UserList } from "./users/UserList";
import { ProjectWorkspaceShell } from "./projects/ProjectWorkspaceShell";
import { ProjectMobileCardList } from "./projects/ProjectList";
import { MobilePageHeader } from "./kit/mobile-page-header";
import { PerformancePage } from "./performance/PerformancePage";
import { SettingsConsolePage } from "./integrations/SettingsConsolePage";
import { ConversationList } from "./conversations/presentation/ConversationList";
import { ConversationShowContent } from "./conversations/presentation/ConversationShow";
import { RecruitingCommandCenter } from "./dashboard/RecruitingCommandCenter";
import { RecordContextProvider } from "ra-core";
import type { Conversation, Project, UserAccount } from "./types";

// --- fixtures -------------------------------------------------------------

const longText = "Nội dung Hiển thị rất dài để thử containment. ".repeat(6);

const user: UserAccount = {
  id: "user-1",
  email: "nguyen.minh.anh.recruitment@vfic.example.org",
  full_name: "Nguyễn Minh Anh",
  role: "recruiter",
  disabled: false,
  created_at: "2026-07-22T10:00:00Z",
  updated_at: "2026-07-22T10:00:00Z",
};

const project: Project = {
  id: "project-1",
  name: "Dự án tuyển dụng với tên rất dài để thử containment ở 320px",
  slug: "du-an-dai",
  is_active: true,
  ingest_state: "ready",
  knowledge_mode: "RAG",
  knowledge_document_count: 6,
  category_readiness: { ready: 12, total: 12 },
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
};

const conversation = {
  id: "conv-1",
  zalo_chat_id: "zalo-1",
  mode: "human",
  needs_human: false,
  assigned_recruiter_id: null,
  last_inbound_at: null,
  created_at: "2026-07-01T00:00:00.000Z",
  updated_at: "2026-07-01T00:00:00.000Z",
  unread_count: 0,
} as Conversation;

const chatMessage = (id: number) => ({
  id: String(id),
  zalo_message_id: String(id),
  conversation_id: "conv-1",
  type: id % 2 === 0 ? "outbound" : "inbound",
  content: `${longText} (tin ${id})`,
  data: null,
  created_at: `2026-07-01T00:00:${String(id).padStart(2, "0")}.000Z`,
});

// --- harness ----------------------------------------------------------------

const Frame = ({ children }: { children: ReactNode }) => (
  <div className="workspace-frame">
    <div className="workspace-frame-content">{children}</div>
  </div>
);

const renderContained = async (
  ui: ReactNode,
  viewportWidth: number,
  viewportHeight: number,
) => {
  await page.viewport(viewportWidth, viewportHeight);
  return render(
    <TestMessages>
      <MemoryRouter>
        <QueryClientProvider client={new QueryClient()}>
          <Frame>{ui}</Frame>
        </QueryClientProvider>
      </MemoryRouter>
    </TestMessages>,
  );
};

const PHONES = [
  { width: 320, height: 568 },
  { width: 390, height: 844 },
] as const;

beforeEach(() => {
  viewport.isMobile = true;
  listState.value = {
    data: [],
    isPending: false,
    error: null,
    total: 0,
    page: 1,
    perPage: 25,
    setPage: () => {},
    filterValues: {},
    displayedFilters: {},
    setFilters: () => {},
    setPerPage: () => {},
    hasNextPage: false,
    hasPreviousPage: false,
  };
  chatState.messages = [];
  apiJson.mockReset();
  apiJson.mockImplementation((url: string) =>
    Promise.resolve(
      url.startsWith("/api/v1/leads")
        ? { data: [], total: 0 }
        : {
            updated_at: "2026-07-12T10:00:00Z",
            counters: {},
            immediate: [],
            today: [],
          },
    ),
  );
});

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

describe("mobile containment", () => {
  it.each(PHONES)(
    "keeps the users directory inside $width×$height",
    async ({ width, height }) => {
      listState.value = {
        ...listState.value,
        data: [user],
        total: 1,
      };
      const screen = await renderContained(<UserList />, width, height);
      await expect.element(screen.getByText("Nguyễn Minh Anh")).toBeVisible();
      expectContained(screen.container, width, ".user-directory-workspace");
    },
  );

  it.each(PHONES)(
    "keeps the project directory inside $width×$height",
    async ({ width, height }) => {
      // The real mobile anatomy: shell + kit header + phone card list. The
      // full `ProjectListContent` pulls react-admin's update/delete controllers
      // whose provider plumbing is out of scope here (its own suites cover
      // it); containment is about the DOM this page renders on a phone.
      const screen = await renderContained(
        <ProjectWorkspaceShell>
          <div className="project-workspace-content">
            <div className="ops-page-shell project-page-shell">
              <MobilePageHeader title="Dự án tuyển dụng" />
              <ProjectMobileCardList
                projects={[project]}
                isAdmin={false}
                canEdit={false}
                onEdit={() => {}}
                onDeleted={() => {}}
                onOpenKnowledge={() => {}}
              />
            </div>
          </div>
        </ProjectWorkspaceShell>,
        width,
        height,
      );
      await expect.element(screen.getByText(project.name)).toBeVisible();
      expectContained(screen.container, width);
    },
  );

  it.each(PHONES)(
    "keeps the performance page inside $width×$height",
    async ({ width, height }) => {
      const screen = await renderContained(<PerformancePage />, width, height);
      await expect
        .element(screen.getByRole("heading", { name: "Hiệu suất chatbot" }))
        .toBeVisible();
      expectContained(screen.container, width, ".performance-page");
    },
  );

  it.each(PHONES)(
    "keeps the settings root and Messenger sub-page inside $width×$height",
    async ({ width, height }) => {
      const screen = await renderContained(
        <SettingsConsolePage />,
        width,
        height,
      );
      await expect
        .element(screen.getByText("Kênh & Tích hợp", { exact: true }))
        .toBeVisible();
      expectContained(screen.container, width, ".settings-workspace-content");

      await screen
        .getByRole("button", { name: "Messenger", exact: true })
        .click();
      await expect
        .element(
          screen.getByRole("heading", { name: "Messenger", exact: true }),
        )
        .toBeVisible();
      expectContained(screen.container, width, ".settings-workspace-content");
    },
  );

  it.each(PHONES)(
    "keeps the inbox list inside $width×$height",
    async ({ width, height }) => {
      listState.value = {
        ...listState.value,
        data: [conversation],
        total: 1,
      };
      const screen = await renderContained(<ConversationList />, width, height);
      expectContained(screen.container, width, ".inbox-bg-container");
    },
  );

  it.each(PHONES)(
    "keeps an open conversation inside $width×$height",
    async ({ width, height }) => {
      chatState.messages = [1, 2, 3].map(chatMessage);
      const screen = await renderContained(
        <div className="inbox-bg-container conversation-workspace conversation-open">
          <div className="app detail-open has-selected-conversation">
            <section className="panel center-panel">
              <RecordContextProvider value={conversation}>
                <ConversationShowContent />
              </RecordContextProvider>
            </section>
          </div>
        </div>,
        width,
        height,
      );
      // The thread mounted far enough to lay out its transcript and composer.
      expect(screen.container.querySelector(".composer")).toBeTruthy();
      expect(screen.container.querySelector(".chat-scroller")).toBeTruthy();
      expectContained(screen.container, width, ".inbox-bg-container");
    },
  );

  it.each(PHONES)(
    "keeps the dashboard inside $width×$height",
    async ({ width, height }) => {
      const screen = await renderContained(
        <div className="dashboard-workspace">
          <section className="dashboard-workspace-content uu-scope">
            <RecruitingCommandCenter />
          </section>
        </div>,
        width,
        height,
      );
      expectContained(screen.container, width, ".dashboard-workspace-content");
    },
  );
});
