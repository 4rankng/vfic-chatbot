import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  loadSettingsBundle: vi.fn(() =>
    Promise.resolve({
      zalo: {
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
      },
      minimax: {
        minimax_api_key: { configured: false },
        minimax_base_url: "",
        minimax_agent_model: "minimax-model",
        minimax_safety_model: "minimax-model",
        minimax_enable: true,
        llm_default_provider: "minimax" as const,
        llm_failover_order: ["minimax", "openrouter", "custom"],
      },
      openRouter: {
        openrouter_api_key: { configured: false },
        openrouter_base_url: "",
        openrouter_agent_model: "deepseek/deepseek-v4-flash",
        openrouter_safety_model: "deepseek/deepseek-v4-flash",
        openrouter_digest_model: "deepseek/deepseek-v4-flash",
        openrouter_enable: false,
        llm_default_provider: "minimax" as const,
        llm_failover_order: ["minimax", "openrouter", "custom"],
      },
      customLlm: {
        custom_llm_api_key: { configured: false },
        custom_llm_base_url: "",
        custom_llm_agent_model: "",
        custom_llm_safety_model: "",
        custom_llm_fast_model: "",
        custom_llm_label: "Dự phòng",
        custom_llm_enable: false,
        custom_llm_usable: false,
        llm_default_provider: "minimax" as const,
        llm_failover_order: ["minimax", "openrouter", "custom"],
      },
    }),
  ),
  testOaConnection: vi.fn(() =>
    Promise.resolve({
      configured: true,
      connected: true,
      missing: [],
      errors: [],
      oa_secret_valid: null,
      oa_refresh_ok: null,
      oa_token_expired: false,
    }),
  ),
  loadFacebookStatus: vi.fn(() =>
    Promise.resolve({ enabled: true, accounts: [] }),
  ),
  loadFacebookCredentials: vi.fn(() =>
    Promise.resolve({
      facebook_app_id: { configured: false, value: null },
      facebook_app_secret: { configured: false, preview: null },
      facebook_login_config_id: { configured: false, value: null },
      facebook_webhook_verify_token: { configured: false, preview: null },
    }),
  ),
  loadFacebookOAuthPages: vi.fn((_flowId: string) =>
    Promise.resolve({
      pages: [{ id: "page-123", name: "Ting Ting Tuyển dụng" }],
      active_page_id: null,
    }),
  ),
  isMobile: false,
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
  usePermissions: () => ({ permissions: "admin", isPending: false }),
  useTranslate: () => (key: string, options?: { _: string }) =>
    options?._ ?? key,
  // The Facebook section of the settings page pulls the Projects list.
  useGetList: () => ({ data: [], total: 0 }),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mocks.isMobile }));
vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    loadSettingsBundle: mocks.loadSettingsBundle,
    saveZaloSettings: vi.fn(),
    saveMinimaxSettings: vi.fn(),
    saveOpenRouterSettings: vi.fn(),
    saveCustomLlmSettings: vi.fn(),
    testBotConnection: vi.fn(),
    testOaConnection: mocks.testOaConnection,
    testMinimaxConnection: vi.fn(),
    testOpenRouterConnection: vi.fn(),
    testCustomLlmConnection: vi.fn(),
  },
  facebookIntegrationGateway: {
    loadStatus: mocks.loadFacebookStatus,
    loadCredentials: mocks.loadFacebookCredentials,
    saveCredentials: vi.fn(),
    loadOAuthPages: mocks.loadFacebookOAuthPages,
    startOAuth: vi.fn(),
    completeOAuth: vi.fn(),
    testConnection: vi.fn(),
    disconnect: vi.fn(),
  },
}));
vi.mock("../personas/PersonaList", () => ({ PersonaList: () => null }));
vi.mock("../users/UserList", () => ({ UserList: () => null }));

import { ZaloIntegrationPage } from "./ZaloIntegrationPage";

afterEach(async () => {
  await cleanup();
  mocks.loadSettingsBundle.mockClear();
  mocks.testOaConnection.mockClear();
  mocks.loadFacebookStatus.mockClear();
  mocks.loadFacebookCredentials.mockClear();
  mocks.loadFacebookOAuthPages.mockClear();
  mocks.notify.mockClear();
  window.history.replaceState(null, "", "/#/settings");
});

describe("ZaloIntegrationPage navigation", () => {
  it("keeps desktop reveal controls available and reports clipboard copy success", async () => {
    mocks.isMobile = false;
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    const input = screen.getByRole("textbox", { name: "Bot Token" });
    await input.fill("secret-token");

    const revealButton = screen.getByRole("button", {
      name: "Hiện Bot Token",
    });
    await expect.element(revealButton).toBeVisible();
    await revealButton.click();
    await expect
      .element(screen.getByRole("textbox", { name: "Bot Token" }))
      .toHaveAttribute("type", "text");

    await screen.getByRole("button", { name: "Sao chép Bot Token" }).click();

    await expect
      .poll(() => clipboardWrite.mock.calls)
      .toEqual([["secret-token"]]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([["Đã sao chép Bot Token.", { type: "success" }]]);
  });

  it("reports clipboard copy failures without crashing the settings form", async () => {
    mocks.isMobile = false;
    const clipboardWrite = vi
      .fn()
      .mockRejectedValue(new Error("Clipboard unavailable"));
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    await screen
      .getByRole("textbox", { name: "Bot Token" })
      .fill("secret-token");
    await screen.getByRole("button", { name: "Sao chép Bot Token" }).click();

    await expect
      .poll(() => clipboardWrite.mock.calls)
      .toEqual([["secret-token"]]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([["Không thể sao chép Bot Token.", { type: "error" }]]);
  });

  it("keeps mobile reveal controls interactive and reports rejected clipboard writes", async () => {
    mocks.isMobile = true;
    const clipboardWrite = vi
      .fn()
      .mockRejectedValue(new Error("Clipboard unavailable"));
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    const input = screen.getByRole("textbox", { name: "Bot Token" });
    await input.fill("mobile-secret");

    const revealButton = screen.getByRole("button", {
      name: "Hiện Bot Token",
    });
    await expect.element(revealButton).toBeVisible();
    await revealButton.click();
    await expect
      .element(screen.getByRole("textbox", { name: "Bot Token" }))
      .toHaveAttribute("type", "text");

    await screen.getByRole("button", { name: "Sao chép Bot Token" }).click();

    await expect
      .poll(() => clipboardWrite.mock.calls)
      .toEqual([["mobile-secret"]]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([["Không thể sao chép Bot Token.", { type: "error" }]]);
  });

  it("uses one flat desktop workspace without a second navigation rail", async () => {
    mocks.isMobile = false;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    const workspace = screen.container.querySelector<HTMLElement>(
      ".settings-workspace",
    )!;
    const app = workspace.querySelector<HTMLElement>(".settings-app")!;
    const center = workspace.querySelector<HTMLElement>(
      ".settings-center-panel",
    )!;
    const navIcon = workspace.querySelector<HTMLElement>(
      ".settings-side-nav-icon",
    )!;

    expect(workspace.querySelector(".inbox-sidebar")).toBeNull();
    expect(workspace.querySelector(".ops-command-mark")).toBeNull();
    expect(getComputedStyle(workspace).backgroundImage).toBe("none");
    expect(getComputedStyle(workspace).padding).toBe("0px");
    expect(getComputedStyle(app).gridTemplateColumns).not.toContain("58px");
    expect(getComputedStyle(app).borderRadius).toBe("0px");
    expect(getComputedStyle(navIcon).borderTopWidth).toBe("0px");
    expect(getComputedStyle(navIcon).backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(center.getBoundingClientRect().width).toBeCloseTo(
      workspace.getBoundingClientRect().width,
      0,
    );
  });

  it("shows compact credential status icons and channel readiness progress", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    const configuredLabel = screen.container.querySelector(
      'label[for="zalo_bot_token"]',
    );
    const configuredRow = configuredLabel?.closest(".settings-field-label-row");
    const configuredStatus = configuredRow?.querySelector(
      ".settings-field-status",
    );

    expect(configuredStatus?.getAttribute("aria-label")).toBe("Đã lưu");
    expect(configuredStatus?.classList.contains("is-configured")).toBe(true);

    const missingLabel = screen.container.querySelector(
      'label[for="zalo_bot_webhook_secret"]',
    );
    const missingRow = missingLabel?.closest(".settings-field-label-row");
    const missingStatus = missingRow?.querySelector(".settings-field-status");

    expect(missingStatus?.getAttribute("aria-label")).toBe("Chưa cấu hình");
    expect(missingStatus?.classList.contains("is-configured")).toBe(false);

    const chatbotGroup = configuredLabel?.closest(".settings-group");
    const progress = chatbotGroup?.querySelector(".settings-group-status");
    expect(
      progress?.querySelector('span[aria-hidden="true"]')?.textContent,
    ).toBe("1/2");
    expect(progress?.querySelector(".sr-only")?.textContent).toBe(
      "1/2 trường đã cấu hình",
    );
  });

  it("reports only the OA credential test result when webhook signature health is mismatched", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    const testButton = screen
      .getByRole("button", { name: "Lưu & kiểm tra" })
      .nth(1);
    await expect.element(testButton).toBeVisible();
    await testButton.click();

    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([["Kết nối Zalo OA thành công", { type: "success" }]]);
  });

  it("opens Messenger and consumes a Facebook OAuth callback on first render", async () => {
    window.history.replaceState(
      null,
      "",
      "/#/settings?section=channels&facebook_oauth_status=pending_selection&facebook_oauth_flow_id=opaque-flow-123&view=compact",
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    await expect
      .element(screen.getByRole("heading", { name: "Messenger", exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("radio", { name: "Ting Ting Tuyển dụng" }))
      .toBeVisible();
    await expect
      .poll(() =>
        mocks.loadFacebookOAuthPages.mock.calls.some(
          ([flowId]) => flowId === "opaque-flow-123",
        ),
      )
      .toBe(true);
    expect(window.location.hash).toBe(
      "#/settings?section=channels&view=compact",
    );
  });

  it("opens the existing Facebook Messenger integration from Settings", async () => {
    mocks.isMobile = false;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    await expect
      .element(screen.getByRole("button", { name: "Zalo", exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: /Messenger/ }))
      .toBeVisible();

    const messengerButton = Array.from(
      screen.container.querySelectorAll<HTMLButtonElement>(
        ".settings-side-nav-link",
      ),
    ).find((button) => button.textContent?.includes("Messenger"));
    expect(messengerButton).toBeDefined();
    messengerButton?.click();

    await expect
      .element(screen.getByRole("heading", { name: "Messenger", exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Kết nối Facebook" }))
      .toBeVisible();

    const settingsShells =
      screen.container.querySelectorAll(".settings-console");
    const settingsMains = screen.container.querySelectorAll(".settings-main");
    const messengerSection = screen.container.querySelector(
      ".settings-main > .settings-section-panel",
    );

    expect(settingsShells).toHaveLength(1);
    expect(settingsMains).toHaveLength(1);
    expect(messengerSection).not.toBeNull();
  });

  it("opens the existing Facebook Messenger integration from the mobile drawer", async () => {
    mocks.isMobile = true;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    await expect
      .element(screen.getByRole("button", { name: "Mở danh mục cài đặt" }))
      .toBeVisible();

    await screen.getByRole("button", { name: "Mở danh mục cài đặt" }).click();

    const messengerButton = await screen.getByRole("button", {
      name: /Messenger/,
    });
    await expect.element(messengerButton).toBeVisible();
    await messengerButton.click();

    await expect
      .element(screen.getByRole("heading", { name: "Messenger", exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Kết nối Facebook" }))
      .toBeVisible();
  });
});

describe("ZaloIntegrationPage provider sections", () => {
  it("opens the AI Providers panel with the failover chain and all three cards", async () => {
    mocks.isMobile = false;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    await expect
      .element(screen.getByRole("button", { name: "Zalo", exact: true }))
      .toBeVisible();

    const providersButton = Array.from(
      screen.container.querySelectorAll<HTMLButtonElement>(
        ".settings-side-nav-link",
      ),
    ).find((button) => button.textContent?.includes("AI Providers"));
    expect(providersButton).toBeDefined();
    providersButton?.click();

    // Panel header + failover chain strip + all three provider cards render.
    await expect
      .element(
        screen.getByRole("heading", { name: "AI Providers", exact: true }),
      )
      .toBeVisible();
    await expect.element(screen.getByText("Thứ tự dự phòng")).toBeVisible();
    // Multiple elements legitimately contain each provider name (order line,
    // card title) — assert the read-only order line specifically.
    await expect
      .element(
        screen.container.querySelector<HTMLElement>(".settings-llm-chain"),
      )
      .toBeVisible();
    await expect
      .element(
        screen.container.querySelector<HTMLElement>(
          ".settings-llm-chain-item.is-default",
        ),
      )
      .toBeVisible();
    // Every provider gets a card, laid out in failover order.
    expect(screen.container.querySelectorAll(".settings-llm-card").length).toBe(
      3,
    );
    await expect
      .element(
        screen.container.querySelector<HTMLElement>(".settings-llm-footer"),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Lưu thay đổi" }))
      .toBeVisible();
  });

  it("reorders the failover chain and flags the change as saveable", async () => {
    mocks.isMobile = false;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ZaloIntegrationPage />
      </QueryClientProvider>,
    );

    await expect
      .element(screen.getByRole("button", { name: "Zalo", exact: true }))
      .toBeVisible();
    const providersButton = Array.from(
      screen.container.querySelectorAll<HTMLButtonElement>(
        ".settings-side-nav-link",
      ),
    ).find((button) => button.textContent?.includes("AI Providers"));
    providersButton?.click();
    await expect
      .element(
        screen.getByRole("heading", { name: "AI Providers", exact: true }),
      )
      .toBeVisible();

    // Two spare providers must be enabled before they can join the chain.
    screen.container
      .querySelector<HTMLButtonElement>("#openrouter_enable")
      ?.click();
    screen.container
      .querySelector<HTMLButtonElement>("#custom_llm_enable")
      ?.click();

    // The cards are the ranking: their board order must track the chain, and
    // the read-only order line must restate it.
    const cardOrder = () =>
      Array.from(
        screen.container.querySelectorAll<HTMLElement>(
          '.settings-llm-card [data-slot="settings-group-title"]',
        ),
      ).map((item) => item.textContent ?? "");
    const chainOrder = () =>
      Array.from(
        screen.container.querySelectorAll<HTMLElement>(
          ".settings-llm-chain-item",
        ),
      ).map((item) => item.textContent ?? "");

    await expect
      .element(screen.getByRole("button", { name: "Tăng ưu tiên cho Xiaomi" }))
      .toBeVisible();
    expect(cardOrder().join("|")).toBe("MiniMax|OpenRouter|Xiaomi");
    expect(chainOrder().join("|")).toBe("1MiniMax|2OpenRouter|3Xiaomi");

    await screen
      .getByRole("button", { name: "Tăng ưu tiên cho Xiaomi" })
      .click();

    await vi.waitFor(() => {
      expect(cardOrder().join("|")).toBe("MiniMax|Xiaomi|OpenRouter");
      expect(chainOrder().join("|")).toBe("1MiniMax|2Xiaomi|3OpenRouter");
    });
    // A reordered chain is a pending edit: save becomes available.
    await expect
      .element(screen.getByRole("button", { name: "Lưu thay đổi" }))
      .not.toBeDisabled();

    // Disabling the default must hand the turn to the operator's next-ranked
    // provider (Xiaomi, just promoted to slot 2) — not to whichever provider
    // happens to come first in the canonical array.
    screen.container
      .querySelector<HTMLButtonElement>("#minimax_enable")
      ?.click();

    await vi.waitFor(() => {
      expect(chainOrder().join("|")).toBe("1Xiaomi|2OpenRouter");
    });
  });
});
