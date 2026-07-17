import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as RuntimeStateModule from "@/components/atomic-crm/root/reset-runtime-state";

const state = vi.hoisted(() => ({
  manifest: {} as Record<string, unknown>,
  failStaticRuntime: false,
}));

vi.mock("@/components/atomic-crm/installation/installation-context", () => ({
  useInstallationContext: () => ({
    manifest: state.manifest,
  }),
}));
vi.mock("@/components/atomic-crm/root/CRM", () => ({
  CRM: () => <p>business-admin</p>,
}));
vi.mock("@/components/atomic-crm/providers/commons/i18nProvider", () => ({
  i18nProvider: {},
}));
vi.mock("@/components/atomic-crm/root/reset-runtime-state", async (importOriginal) => {
  const actual = await importOriginal<typeof RuntimeStateModule>();
  return {
    ...actual,
    ensureRuntimeGeneration: async (...args: Parameters<typeof actual.ensureRuntimeGeneration>) => {
      if (state.failStaticRuntime) throw new Error("Static runtime failed");
      return actual.ensureRuntimeGeneration(...args);
    },
  };
});

import App, { RecruitmentWorkspaceLoading } from "./App";
import {
  abandonRuntimeGenerationForTests,
  resetActiveRuntimeState,
} from "./components/atomic-crm/root/reset-runtime-state";

afterEach(async () => {
  await cleanup();
  await resetActiveRuntimeState();
  abandonRuntimeGenerationForTests();
  state.failStaticRuntime = false;
});

describe("application lifecycle composition", () => {
  it("announces the recruitment workspace loading state", async () => {
    const screen = await render(<RecruitmentWorkspaceLoading />);
    await expect.element(screen.getByRole("status")).toHaveTextContent("Đang chuẩn bị không gian tuyển dụng");
    await expect.element(screen.getByRole("main")).toHaveAttribute("aria-live", "polite");
  });
  it.each(["UNCONFIGURED", "DRAFT", "VALIDATED", "SUSPENDED", "UPGRADE_REQUIRED"])(
    "opens the recruitment console without an installation screen for %s",
    async (lifecycle) => {
      state.manifest = { lifecycle, readiness_code: "SETUP_REQUIRED", authority_generation: 0 };
      const screen = await render(<App />);
      await expect.element(screen.getByText("business-admin")).toBeVisible();
    },
  );

  it("mounts business Admin only for a ready ACTIVE runtime", async () => {
    state.manifest = { lifecycle: "ACTIVE", readiness_code: "READY", authority_generation: 1 };
    const screen = await render(<App />);
    await expect.element(screen.getByText("business-admin")).toBeVisible();
  });

  it("opens the static recruitment console for a legacy workspace", async () => {
    state.manifest = {
      lifecycle: "UNCONFIGURED",
      readiness_code: "SETUP_REQUIRED",
      legacy_workspace: true,
      authority_generation: 0,
    };
    const screen = await render(<App />);

    await expect.element(screen.getByText("business-admin")).toBeVisible();
  });

  it("shows a reload action when static recruitment runtime creation fails", async () => {
    state.manifest = { lifecycle: "ACTIVE", readiness_code: "READY", authority_generation: 1 };
    state.failStaticRuntime = true;
    const screen = await render(<App />);

    await expect.element(
      screen.getByRole("heading", { name: "Không thể tải không gian tuyển dụng" }),
    ).toBeVisible();
    await expect.element(screen.getByText("business-admin")).not.toBeInTheDocument();
    await expect.element(screen.getByRole("button", { name: "Tải lại trang" })).toBeVisible();
  });
});
