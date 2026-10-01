import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { cleanup, renderHook } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  saveZalo: vi.fn(),
  testBot: vi.fn(),
  testOa: vi.fn(),
  saveMinimax: vi.fn(),
  testMinimax: vi.fn(),
}));
vi.mock("ra-core", () => ({ useNotify: () => mocks.notify }));
vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    saveZaloSettings: mocks.saveZalo,
    testBotConnection: mocks.testBot,
    testOaConnection: mocks.testOa,
    saveMinimaxSettings: mocks.saveMinimax,
    testMinimaxConnection: mocks.testMinimax,
  },
}));

import type { ZaloSettings } from "./api";
import type { ProviderSettingsBundle } from "./providerDescriptors";
import { useProviderPanels } from "./useProviderPanels";
import { useZaloForm } from "./useZaloForm";

const secret = { configured: true };
const settings: ZaloSettings = {
  zalo_bot_token: secret,
  zalo_bot_webhook_secret: secret,
  zalo_oa_app_id: { configured: true, value: "saved-app" },
  zalo_oa_secret_key: secret,
  zalo_oa_access_token: secret,
  zalo_oa_refresh_token: secret,
  zalo_bot_api_base: "",
  zalo_oa_api_base: "",
  zalo_oa_webhook_signature: null,
};
const chain = {
  llm_default_provider: "minimax" as const,
  llm_failover_order: ["minimax", "openrouter", "custom"] as const,
};
const providers: ProviderSettingsBundle = {
  minimax: {
    ...chain,
    llm_failover_order: [...chain.llm_failover_order],
    minimax_api_key: secret,
    minimax_base_url: "",
    minimax_agent_model: "model",
    minimax_extractor_model: "model",
    minimax_enable: true,
    last_test: null,
  },
  openRouter: {
    ...chain,
    llm_failover_order: [...chain.llm_failover_order],
    openrouter_api_key: secret,
    openrouter_base_url: "",
    openrouter_agent_model: "model",
    openrouter_extractor_model: "model",
    openrouter_digest_model: "model",
    openrouter_enable: false,
    embedding_provider: "openrouter",
    embedding_gemini_api_key: secret,
    last_test: null,
  },
  customLlm: {
    ...chain,
    llm_failover_order: [...chain.llm_failover_order],
    custom_llm_api_key: secret,
    custom_llm_base_url: "",
    custom_llm_agent_model: "model",
    custom_llm_fast_model: "model",
    custom_llm_label: "Xiaomi",
    custom_llm_enable: false,
    custom_llm_usable: false,
    last_test: null,
  },
  jev: {
    jev_api_key: secret,
    jev_model: "model",
    jev_enable: false,
    jev_usable: false,
  },
};
let queryClient: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  mocks.saveZalo.mockResolvedValue(settings);
  mocks.testBot.mockResolvedValue({
    connected: true,
    configured: true,
    missing: [],
    errors: [],
  });
  mocks.saveMinimax.mockResolvedValue(providers.minimax);
});
afterEach(async () => {
  await cleanup();
  queryClient.clear();
});

describe("settings draft integrity", () => {
  it("preserves the OA draft when only bot credentials are saved and tested", async () => {
    const hook = await renderHook(() => useZaloForm({ settings }), { wrapper });
    await hook.act(() => {
      hook.result.current.setValue("zalo_bot_token", "new-bot-token");
      hook.result.current.setValue("zalo_oa_access_token", "unsaved-oa-token");
    });
    await hook.act(async () => {
      await hook.result.current.testChannel("bot");
    });
    expect(mocks.saveZalo).toHaveBeenCalledWith({
      zalo_bot_token: "new-bot-token",
    });
    expect(hook.result.current.form.zalo_bot_token).toBe("");
    expect(hook.result.current.form.zalo_oa_access_token).toBe(
      "unsaved-oa-token",
    );
  });

  it("reports a failed channel test and releases pending state without throwing", async () => {
    mocks.testBot.mockRejectedValueOnce(new Error("Unavailable"));
    const hook = await renderHook(() => useZaloForm({ settings }), { wrapper });
    await hook.act(async () => {
      await hook.result.current.testChannel("bot");
    });
    expect(hook.result.current.channelTesting.bot).toBe(false);
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.stringContaining("Vui lòng thử lại"),
      { type: "error" },
    );
  });

  it("keeps standalone provider edits through chain save and discard", async () => {
    const hook = await renderHook(() => useProviderPanels(providers), {
      wrapper,
    });
    await expect
      .poll(() => hook.result.current.providerForm.jev_model)
      .toBe("model");
    await hook.act(() => {
      hook.result.current.setProviderFormValue(
        "jev_api_key",
        "unsaved-jev-key",
      );
      hook.result.current.setProviderFormValue(
        "minimax_api_key",
        "new-minimax-key",
      );
    });
    await hook.act(async () => {
      await hook.result.current.saveProviderPanels("chain");
    });
    expect(hook.result.current.providerForm.jev_api_key).toBe(
      "unsaved-jev-key",
    );
    await hook.act(() => {
      hook.result.current.setProviderFormValue(
        "minimax_api_key",
        "discard-this-key",
      );
      hook.result.current.discardProviderPanels("chain");
    });
    expect(hook.result.current.providerForm.jev_api_key).toBe(
      "unsaved-jev-key",
    );
    expect(hook.result.current.providerForm.minimax_api_key).toBe("");
  });

  it("records a failed provider test and releases pending state without throwing", async () => {
    mocks.testMinimax.mockRejectedValueOnce(new Error("Unavailable"));
    const hook = await renderHook(() => useProviderPanels(providers), {
      wrapper,
    });
    await hook.act(async () => {
      await hook.result.current.testProviderPanel("minimax");
    });
    expect(hook.result.current.providerTesting.minimax).toBe(false);
    expect(hook.result.current.providerLastTests.minimax?.ok).toBe(false);
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.stringContaining("Vui lòng thử lại"),
      { type: "error" },
    );
  });
});
