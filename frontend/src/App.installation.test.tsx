import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  manifest: {} as Record<string, unknown>,
  refreshRuntime: vi.fn(async () => undefined),
}));

vi.mock("@/components/atomic-crm/installation/installation-context", () => ({
  useInstallationContext: () => ({
    manifest: state.manifest,
    refreshRuntime: state.refreshRuntime,
  }),
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

import App, { RuntimeCompilationLoading } from "./App";
import { readyRecruitmentManifest } from "./components/atomic-crm/capabilities/test-fixtures";
import {
  abandonRuntimeGenerationForTests,
  resetActiveRuntimeState,
} from "./components/atomic-crm/root/reset-runtime-state";

afterEach(async () => {
  await cleanup();
  await resetActiveRuntimeState();
  abandonRuntimeGenerationForTests();
  state.refreshRuntime.mockClear();
});

describe("application lifecycle composition", () => {
  it("announces the neutral runtime compilation state", async () => {
    const screen = await render(<RuntimeCompilationLoading />);
    await expect.element(screen.getByRole("status")).toHaveTextContent("Đang chuẩn bị không gian làm việc");
    await expect.element(screen.getByRole("main")).toHaveAttribute("aria-live", "polite");
  });
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
    state.manifest = readyRecruitmentManifest();
    const screen = await render(<App />);
    await expect.element(screen.getByText("business-admin")).toBeVisible();
    await expect.element(screen.getByText("setup-only-shell")).not.toBeInTheDocument();
  });

  it("fails closed with an explicit retry when a ready manifest cannot compile", async () => {
    state.manifest = readyRecruitmentManifest({
      authority_generation: 2,
      pack_contract_hash: "f".repeat(64),
    });
    const screen = await render(<App />);

    await expect.element(
      screen.getByRole("heading", { name: "Không thể mở không gian làm việc" }),
    ).toBeVisible();
    await expect.element(screen.getByText("business-admin")).not.toBeInTheDocument();
    await screen.getByRole("button", { name: "Kiểm tra lại cấu hình" }).click();
    expect(state.refreshRuntime).toHaveBeenCalledOnce();
  });
});
