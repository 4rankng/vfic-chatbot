import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  configuration: {} as Record<string, unknown>,
  getConfiguration: vi.fn(),
  updateConfiguration: vi.fn(),
  useQuery: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useDataProvider: () => ({ getConfiguration: mocks.getConfiguration }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: unknown) => {
    mocks.useQuery(options);
    return { data: mocks.configuration };
  },
}));

vi.mock("./ConfigurationContext", () => ({
  useConfigurationUpdater: () => mocks.updateConfiguration,
}));

import { useConfigurationLoader } from "./useConfigurationLoader";

const renderLoader = () => {
  const container = document.createElement("div");
  const root = createRoot(container);
  const Harness = () => {
    useConfigurationLoader();
    return null;
  };
  act(() => root.render(createElement(Harness)));
  return () => act(() => root.unmount());
};

describe("legacy configuration loader migration oracle", () => {
  beforeEach(() => {
    mocks.configuration = {};
    mocks.getConfiguration.mockReset();
    mocks.updateConfiguration.mockReset();
    mocks.useQuery.mockReset();
  });

  it("queries the data provider under the configuration cache key", async () => {
    const unmount = renderLoader();

    const options = mocks.useQuery.mock.calls[0][0] as {
      queryKey: string[];
      queryFn: () => Promise<unknown>;
      retry: boolean;
    };
    expect(options.queryKey).toEqual(["configuration"]);
    expect(options.retry).toBe(false);
    await options.queryFn();
    expect(mocks.getConfiguration).toHaveBeenCalledOnce();
    unmount();
  });

  it("ignores an empty server configuration", () => {
    const unmount = renderLoader();
    expect(mocks.updateConfiguration).not.toHaveBeenCalled();
    unmount();
  });

  it("merges a non-empty server configuration into browser state", () => {
    mocks.configuration = { title: "Configured customer" };
    const unmount = renderLoader();
    expect(mocks.updateConfiguration).toHaveBeenCalledWith(mocks.configuration);
    unmount();
  });
});
