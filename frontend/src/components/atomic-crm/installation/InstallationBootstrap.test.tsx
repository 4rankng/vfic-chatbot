import { cleanup, render } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchRuntimeManifest: vi.fn(),
  applyRuntimeMetadata: vi.fn(),
  resetRuntimeMetadata: vi.fn(),
}));

vi.mock("./runtime-manifest", () => ({
  fetchRuntimeManifest: mocks.fetchRuntimeManifest,
}));
vi.mock("../root/runtime-metadata", () => ({
  applyRuntimeMetadata: mocks.applyRuntimeMetadata,
  resetRuntimeMetadata: mocks.resetRuntimeMetadata,
}));

import { InstallationBootstrap } from "./InstallationBootstrap";

const manifest = {
  schema_version: 1,
  lifecycle: "UNCONFIGURED",
  authority_generation: 0,
  revision_id: null,
  pack_key: null,
  pack_version: null,
  pack_contract_hash: null,
  manifest_checksum: null,
  customer_identity: null,
  branding: null,
  locale: null,
  timezone: null,
  currency: null,
  terminology: null,
  capability_ids: [],
  readiness_code: "SETUP_REQUIRED",
};

describe("InstallationBootstrap", () => {
  beforeEach(() => {
    window.localStorage.setItem("app.configuration", "old-customer");
  });

  afterEach(async () => {
    await cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("fails closed after bounded runtime failures and exposes an explicit retry", async () => {
    mocks.fetchRuntimeManifest.mockRejectedValueOnce(new Error("network"));
    mocks.fetchRuntimeManifest.mockRejectedValueOnce(new Error("invalid schema"));
    mocks.fetchRuntimeManifest.mockResolvedValueOnce(manifest);

    const screen = await render(
      <InstallationBootstrap>
        <p>customer application</p>
      </InstallationBootstrap>,
    );

    await expect.element(screen.getByText("Không thể xác minh cấu hình")).toBeVisible();
    await expect.element(screen.getByText("customer application")).not.toBeInTheDocument();
    expect(mocks.fetchRuntimeManifest).toHaveBeenCalledTimes(2);

    await screen.getByRole("button", { name: "Thử lại" }).click();
    await expect.element(screen.getByText("customer application")).toBeVisible();
    expect(mocks.fetchRuntimeManifest).toHaveBeenCalledTimes(3);
    expect(mocks.applyRuntimeMetadata).toHaveBeenCalledWith(manifest);
  });

  it("purges the legacy browser configuration before rendering children", async () => {
    mocks.fetchRuntimeManifest.mockResolvedValue(manifest);
    const screen = await render(
      <InstallationBootstrap>
        <p>safe child</p>
      </InstallationBootstrap>,
    );

    await expect.element(screen.getByText("safe child")).toBeVisible();
    expect(window.localStorage.getItem("app.configuration")).toBeNull();
  });
});
