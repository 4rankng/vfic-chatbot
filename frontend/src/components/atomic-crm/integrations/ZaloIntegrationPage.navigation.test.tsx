import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn((path: string) => {
    if (path.endsWith("/zalo")) {
      return Promise.resolve({
        zalo_bot_token: { configured: false },
        zalo_bot_webhook_secret: { configured: false },
        zalo_oa_app_id: { configured: false, value: "" },
        zalo_oa_secret_key: { configured: false },
        zalo_oa_access_token: { configured: false },
        zalo_oa_refresh_token: { configured: false },
        zalo_bot_api_base: "",
        zalo_oa_api_base: "",
        zalo_oa_webhook_signature: null,
      });
    }
    if (path.endsWith("/minimax")) {
      return Promise.resolve({
        minimax_api_key: { configured: false },
        minimax_base_url: "",
        minimax_agent_model: "minimax-model",
        minimax_safety_model: "minimax-model",
        minimax_enable: true,
        llm_default_provider: "minimax",
      });
    }
    if (path.endsWith("/openrouter")) {
      return Promise.resolve({
        openrouter_api_key: { configured: false },
        openrouter_base_url: "",
        openrouter_agent_model: "deepseek/deepseek-v4-flash",
        openrouter_safety_model: "deepseek/deepseek-v4-flash",
        openrouter_digest_model: "deepseek/deepseek-v4-flash",
        openrouter_enable: false,
        llm_default_provider: "minimax",
      });
    }
    if (path.endsWith("/facebook")) {
      return Promise.resolve({ enabled: true, accounts: [] });
    }
    if (path.startsWith("/api/v1/admin/integrations/facebook/oauth/pages?")) {
      return Promise.resolve({
        pages: [{ id: "page-123", name: "Ting Ting Tuyển dụng" }],
        active_page_id: null,
      });
    }
    return Promise.reject(new Error(`Unexpected API path: ${path}`));
  }),
  isMobile: false,
}));

vi.mock("ra-core", () => ({
  useNotify: () => vi.fn(),
  usePermissions: () => ({ permissions: "admin", isPending: false }),
  useTranslate: () => (key: string, options?: { _: string }) =>
    options?._ ?? key,
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => mocks.isMobile }));
vi.mock("../providers/rest/api", () => ({ apiJson: mocks.apiJson }));
vi.mock("../conversations/InboxIcons", () => ({ InboxIcons: () => null }));
vi.mock("../personas/PersonaList", () => ({ PersonaList: () => null }));
vi.mock("../users/UserList", () => ({ UserList: () => null }));

import { ZaloIntegrationPage } from "./ZaloIntegrationPage";

afterEach(async () => {
  await cleanup();
  mocks.apiJson.mockClear();
  window.history.replaceState(null, "", "/#/settings");
});

describe("ZaloIntegrationPage navigation", () => {
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
      .element(screen.getByRole("heading", { name: "Facebook Messenger" }))
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("radio", { name: "Ting Ting Tuyển dụng" }),
      )
      .toBeVisible();
    await expect
      .poll(() =>
        mocks.apiJson.mock.calls.some(
          ([path]) =>
            path ===
            "/api/v1/admin/integrations/facebook/oauth/pages?flow_id=opaque-flow-123",
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
      .element(screen.getByRole("heading", { name: "Facebook Messenger" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Kết nối Facebook" }))
      .toBeVisible();
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
      .element(screen.getByRole("heading", { name: "Facebook Messenger" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Kết nối Facebook" }))
      .toBeVisible();
  });
});
