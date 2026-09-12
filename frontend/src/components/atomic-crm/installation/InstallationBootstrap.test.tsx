import { cleanup, render } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";

const mocks = vi.hoisted(() => ({
  fetchRuntimeManifest: vi.fn(),
  applyRuntimeMetadata: vi.fn(),
  resetRuntimeMetadata: vi.fn(),
  resetActiveRuntimeState: vi.fn(),
}));

vi.mock("./runtime-manifest", () => ({
  fetchRuntimeManifest: mocks.fetchRuntimeManifest,
}));
vi.mock("../root/runtime-metadata", () => ({
  applyRuntimeMetadata: mocks.applyRuntimeMetadata,
  resetRuntimeMetadata: mocks.resetRuntimeMetadata,
}));
vi.mock("../root/reset-runtime-state", () => ({
  resetActiveRuntimeState: mocks.resetActiveRuntimeState,
}));

import { InstallationBootstrap } from "./InstallationBootstrap";
import { useInstallationContext } from "./installation-context";

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
  legacy_workspace: false,
};

const manifestWithGeneration = (authorityGeneration: number) => ({
  ...manifest,
  authority_generation: authorityGeneration,
});

describe("InstallationBootstrap", () => {
  beforeEach(() => {
    window.localStorage.setItem("app.configuration", "old-customer");
  });

  afterEach(async () => {
    await cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("keeps the recruitment console available when runtime metadata is unavailable", async () => {
    mocks.fetchRuntimeManifest.mockRejectedValueOnce(new Error("network"));
    mocks.fetchRuntimeManifest.mockRejectedValueOnce(
      new Error("invalid schema"),
    );

    const screen = await render(
      <InstallationBootstrap>
        <p>customer application</p>
      </InstallationBootstrap>,
    );

    await expect
      .element(screen.getByText("customer application"))
      .toBeVisible();
    expect(mocks.fetchRuntimeManifest).toHaveBeenCalledTimes(2);
    expect(mocks.applyRuntimeMetadata).not.toHaveBeenCalled();
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

  it("resets the previous authority generation before publishing a focus refresh", async () => {
    const trace: string[] = [];
    mocks.fetchRuntimeManifest
      .mockResolvedValueOnce(manifestWithGeneration(4))
      .mockResolvedValueOnce(manifestWithGeneration(5));
    mocks.resetActiveRuntimeState.mockImplementation(async () => {
      trace.push("reset");
    });
    mocks.applyRuntimeMetadata.mockImplementation((nextManifest) => {
      trace.push(`metadata:${nextManifest.authority_generation}`);
    });
    const AuthorityGeneration = () => {
      const { manifest: currentManifest } = useInstallationContext();
      useEffect(() => {
        trace.push(`child:${currentManifest.authority_generation}`);
      }, [currentManifest.authority_generation]);
      return <p>generation {currentManifest.authority_generation}</p>;
    };

    const screen = await render(
      <InstallationBootstrap>
        <AuthorityGeneration />
      </InstallationBootstrap>,
    );

    await expect.element(screen.getByText("generation 4")).toBeVisible();
    window.dispatchEvent(new Event("focus"));
    await expect.element(screen.getByText("generation 5")).toBeVisible();

    expect(mocks.resetActiveRuntimeState).toHaveBeenCalledTimes(1);
    expect(trace.indexOf("reset")).toBeLessThan(trace.indexOf("metadata:5"));
    expect(trace.indexOf("reset")).toBeLessThan(trace.indexOf("child:5"));
  });
});
