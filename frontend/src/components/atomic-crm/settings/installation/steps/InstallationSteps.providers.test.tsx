import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as SetupAuthoringClientModule from "../../../installation/setup-authoring-client";
import type { InstallationCatalog } from "../../../installation/installation-client";

const mocks = vi.hoisted(() => ({
  getModelIntegrationStatus: vi.fn(),
  saveModelIntegrationSecret: vi.fn(),
}));

vi.mock("../../../installation/setup-authoring-client", async (importOriginal) => {
  const actual = await importOriginal<typeof SetupAuthoringClientModule>();
  return {
    ...actual,
    getModelIntegrationStatus: mocks.getModelIntegrationStatus,
    saveModelIntegrationSecret: mocks.saveModelIntegrationSecret,
  };
});

import { ProvidersIntegrationsStep } from "./InstallationSteps";

const catalog: InstallationCatalog = {
  schema_version: 1,
  packs: [],
  capabilities: [],
  locales: [],
  currencies: [],
  workflows: [],
  authored_workflow_versions: [],
  integration_keys: ["minimax", "openrouter"],
  authentication_methods: ["email_password"],
};

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
});

describe("ProvidersIntegrationsStep", () => {
  it("does not repeat the fixed authentication method as a setup control", async () => {
    const screen = await render(
      <ProvidersIntegrationsStep catalog={catalog} issues={[]} onChange={vi.fn()} />,
    );

    await expect.element(screen.getByText("Nhà cung cấp chat")).toBeVisible();
    await expect
      .element(screen.getByText("Phương thức xác thực"))
      .not.toBeInTheDocument();
    await expect
      .element(
        screen.getByText("Email và mật khẩu (phương thức quản trị duy nhất được hỗ trợ)"),
      )
      .not.toBeInTheDocument();
  });

  it("shows a provider API key as a flat field instead of a nested card", async () => {
    mocks.getModelIntegrationStatus.mockResolvedValue({
      openrouter_api_key: { configured: true },
    });

    const screen = await render(
      <ProvidersIntegrationsStep
        catalog={catalog}
        issues={[]}
        onChange={vi.fn()}
        value={{
          provider_policy: {
            chat_integration_key: "openrouter",
            chat_model: "openai/gpt-4.1-mini",
            embedding_integration_key: "openrouter",
            embedding_model: "openai/text-embedding-3-large",
            temperature: 1,
            max_output_tokens: 2048,
          },
          integration_requirements: [],
          authentication_policy: { email_password_enabled: true },
        }}
      />,
    );

    await expect.element(screen.getByLabelText("OpenRouter API Key")).toBeVisible();
    await expect.element(screen.getByText("Đã có khóa được mã hóa")).toBeVisible();
    await expect.element(screen.getByRole("button", { name: "Lưu khóa" })).not.toBeInTheDocument();
    await expect.element(screen.getByRole("button", { name: "Kiểm tra" })).not.toBeInTheDocument();
    await expect
      .element(screen.getByRole("heading", { name: "openrouter" }))
      .not.toBeInTheDocument();
  });

  it("uses the same flat API-key field for MiniMax", async () => {
    mocks.getModelIntegrationStatus.mockResolvedValue({
      minimax_api_key: { configured: true },
    });

    const screen = await render(
      <ProvidersIntegrationsStep
        catalog={catalog}
        issues={[]}
        onChange={vi.fn()}
        value={{
          provider_policy: {
            chat_integration_key: "minimax",
            chat_model: "MiniMax-M2.5",
            embedding_integration_key: "openrouter",
            embedding_model: "openai/text-embedding-3-large",
            temperature: 1,
            max_output_tokens: 2048,
          },
          integration_requirements: [],
          authentication_policy: { email_password_enabled: true },
        }}
      />,
    );

    await expect.element(screen.getByLabelText("MiniMax API Key")).toBeVisible();
    await expect.element(screen.getByRole("heading", { name: "minimax" })).not.toBeInTheDocument();
  });

  it("registers entered API keys for the wizard's primary continue action", async () => {
    mocks.getModelIntegrationStatus.mockResolvedValue({
      openrouter_api_key: { configured: false },
    });
    mocks.saveModelIntegrationSecret.mockResolvedValue(undefined);
    const registeredSavers: Array<(() => Promise<boolean>) | null> = [];

    const screen = await render(
      <ProvidersIntegrationsStep
        catalog={catalog}
        issues={[]}
        onChange={vi.fn()}
        onRegisterSecretSaver={(save) => registeredSavers.push(save)}
        value={{
          provider_policy: {
            chat_integration_key: "openrouter",
            chat_model: "openai/gpt-4.1-mini",
            embedding_integration_key: "openrouter",
            embedding_model: "openai/text-embedding-3-large",
            temperature: 1,
            max_output_tokens: 2048,
          },
          integration_requirements: [],
          authentication_policy: { email_password_enabled: true },
        }}
      />,
    );
    await screen.getByLabelText("OpenRouter API Key").fill("sk-test");
    const save = registeredSavers.filter(
      (value): value is () => Promise<boolean> => value !== null,
    ).at(-1);

    await expect(save?.()).resolves.toBe(true);
    expect(mocks.saveModelIntegrationSecret).toHaveBeenCalledWith("openrouter", "sk-test");
  });
});
