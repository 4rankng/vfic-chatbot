import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstallationCatalog } from "../../../installation/installation-client";
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

    await expect.element(screen.getByText("Bí mật không nằm trong bản nháp")).toBeVisible();
    await expect
      .element(screen.getByText("Phương thức xác thực"))
      .not.toBeInTheDocument();
    await expect
      .element(
        screen.getByText("Email và mật khẩu (phương thức quản trị duy nhất được hỗ trợ)"),
      )
      .not.toBeInTheDocument();
  });
});
