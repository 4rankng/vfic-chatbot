import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "vitest-browser-react";
import { describe, it, vi } from "vitest";

vi.mock("ra-core", () => ({
  useTranslate: (key: string) => key,
  useNotify: () => vi.fn(),
  usePermissions: () => ({ permissions: "admin", isPending: false }),
  useGetList: () => ({ data: [], total: 0 }),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => false }));
vi.mock("../personas/PersonaList", () => ({ PersonaList: () => null }));
vi.mock("../users/UserList", () => ({ UserList: () => null }));
vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    loadZaloSettings: () =>
      Promise.resolve({
        zalo_bot_token: { configured: true, preview: "dev-…oken" },
        zalo_bot_webhook_secret: { configured: false },
        zalo_oa_app_id: { configured: false, value: "" },
        zalo_oa_secret_key: { configured: false },
        zalo_oa_access_token: { configured: false },
        zalo_oa_refresh_token: { configured: false },
        zalo_bot_api_base: "",
        zalo_oa_api_base: "",
        zalo_oa_webhook_signature: { last_status: "verified" },
      }),
    loadMinimaxSettings: () =>
      Promise.resolve({
        minimax_api_key: { configured: false },
        minimax_enable: true,
        llm_default_provider: "minimax",
        llm_failover_order: ["minimax"],
      }),
    loadOpenRouterSettings: () =>
      Promise.resolve({ openrouter_enable: false }),
    loadCustomLlmSettings: () => Promise.resolve({ custom_llm_enable: false }),
    loadJevSettings: () => Promise.resolve({ jev_api_key: { configured: false } }),
    loadTingtingSettings: () =>
      Promise.resolve({
        api_key: { configured: true, preview: "••••••••47 ký tự" },
        configured: true,
        base_url: "https://api.tingting.vn",
        auth_header: "X-API-Key",
        reset_oa_id: "",
        oa_app_id: "2017418346033879562",
        oa_secret_key: { configured: true, preview: "••••20 ký tự" },
        oa_access_token: { configured: true, preview: "••••428 ký tự" },
        oa_refresh_token: { configured: true, preview: "••••423 ký tự" },
        oa_linked: true,
        oa_id: "3383849659955472174",
        oa_name: "Ting Ting Software Solution",
        oa_label: "",
        oa_verified_at: null,
        oa_last_checked_at: null,
        oa_last_error: "",
      }),
  },
  facebookIntegrationGateway: {},
}));

import { SettingsConsolePage } from "./SettingsConsolePage";

describe("tingting look", () => {
  it("renders", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={client}>
        <SettingsConsolePage />
      </QueryClientProvider>,
    );
    const nav = screen.container.querySelectorAll<HTMLButtonElement>(
      ".settings-side-nav-link",
    );
    const target = Array.from(nav).find((b) =>
      b.textContent?.includes("TingTing"),
    );
    target?.click();
    await new Promise((r) => setTimeout(r, 300));
  });
});
