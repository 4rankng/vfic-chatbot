import { createElement } from "react";
import { MemoryRouter, Routes, Route } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const kernelTestState = vi.hoisted(() => {
  let settled = false;
  let release: (() => void) | null = null;
  let pending = Promise.resolve();

  const createDeferred = () => {
    pending = new Promise<void>((resolve) => {
      release = () => {
        settled = true;
        resolve();
      };
    });
  };

  createDeferred();

  return {
    releasePerformance: () => release?.(),
    isPerformanceReady: () => settled,
    resetPerformance: () => {
      settled = false;
      createDeferred();
    },
    permissions: "admin" as "admin" | "recruiter",
    isPending: false,
    get pending() {
      return pending;
    },
  };
});

vi.mock("ra-core", () => ({
  usePermissions: () => ({
    permissions: kernelTestState.permissions,
    isPending: kernelTestState.isPending,
  }),
}));

vi.mock("../../performance/PerformancePage", () => ({
  PerformancePage: () => {
    if (!kernelTestState.isPerformanceReady()) {
      throw kernelTestState.pending;
    }

    return createElement("h1", null, "Trang hiệu suất");
  },
}));

import kernelSource from "./index.tsx?raw";
import { contributions } from "./index";

afterEach(async () => {
  await cleanup();
  kernelTestState.permissions = "admin";
  kernelTestState.isPending = false;
});

describe("kernel capability routes", () => {
  it("keeps Performance out of the primary mobile dock while leaving it rail-eligible", () => {
    const performance = contributions["kernel.navigation.performance"];

    expect(performance.kind).toBe("navigation");
    if (performance.kind !== "navigation") {
      throw new Error("Expected performance navigation contribution");
    }

    expect(performance.destination.mobile).toBe(false);
    expect(performance.destination.rail).toBe(true);
  });

  it("lazy-loads the Performance page behind a non-blank suspense fallback", () => {
    expect(kernelSource).not.toContain(
      'import { PerformancePage } from "../../performance/PerformancePage";',
    );
    expect(kernelSource).not.toContain("<Suspense fallback={null}>");
    expect(kernelSource).toContain('role="status"');
  });

  it("shows the live route fallback while the lazy Performance route is deferred, then resolves", async () => {
    const performance = contributions["kernel.route.performance"];

    expect(performance.kind).toBe("route");
    if (performance.kind !== "route") {
      throw new Error("Expected performance route contribution");
    }

    kernelTestState.resetPerformance();
    const screen = await render(
      createElement(
        MemoryRouter,
        { initialEntries: ["/hieu-suat"] },
        createElement(
          Routes,
          null,
          createElement(Route, {
            path: "/hieu-suat",
            element: createElement(performance.route.Component),
          }),
        ),
      ),
    );

    await expect
      .element(screen.getByRole("status"))
      .toHaveTextContent("Đang tải trang...");
    expect(screen.container.textContent).not.toContain("Trang hiệu suất");

    kernelTestState.releasePerformance();

    await expect
      .element(screen.getByRole("heading", { name: "Trang hiệu suất" }))
      .toBeVisible();
    expect(screen.container.querySelector('[role="status"]')).toBeNull();
  });
});
