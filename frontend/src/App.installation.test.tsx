import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  manifest: {} as Record<string, unknown>,
}));

vi.mock("@/components/atomic-crm/installation/installation-context", () => ({
  useInstallationContext: () => ({ manifest: state.manifest }),
  hasReadyActiveRuntime: (manifest: { lifecycle?: string; readiness_code?: string }) =>
    manifest.lifecycle === "ACTIVE" && manifest.readiness_code === "READY",
}));
vi.mock("@/components/atomic-crm/installation/SetupLayout", () => ({
  SetupApplication: () => <p>setup-only-shell</p>,
}));
vi.mock("@/components/atomic-crm/root/CRM", () => ({
  CRM: () => <p>business-admin</p>,
}));
vi.mock("@/components/atomic-crm/providers/commons/i18nProvider", () => ({
  createI18nProvider: () => ({}),
}));

import App from "./App";

afterEach(async () => {
  await cleanup();
});

describe("application lifecycle composition", () => {
  it.each(["UNCONFIGURED", "DRAFT", "VALIDATED", "SUSPENDED", "UPGRADE_REQUIRED"])(
    "mounts only the setup shell for %s",
    async (lifecycle) => {
      state.manifest = { lifecycle, readiness_code: "SETUP_REQUIRED", locale: null };
      const screen = await render(<App />);
      await expect.element(screen.getByText("setup-only-shell")).toBeVisible();
      await expect.element(screen.getByText("business-admin")).not.toBeInTheDocument();
    },
  );

  it("mounts business Admin only for a ready ACTIVE runtime", async () => {
    state.manifest = { lifecycle: "ACTIVE", readiness_code: "READY", locale: "vi-VN" };
    const screen = await render(<App />);
    await expect.element(screen.getByText("business-admin")).toBeVisible();
    await expect.element(screen.getByText("setup-only-shell")).not.toBeInTheDocument();
  });
});
