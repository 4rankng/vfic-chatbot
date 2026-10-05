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

  let performanceModuleEvaluations = 0;

  return {
    releasePerformance: () => release?.(),
    isPerformanceReady: () => settled,
    markPerformanceModuleEvaluated: () => {
      performanceModuleEvaluations += 1;
    },
    performanceModuleEvaluations: () => performanceModuleEvaluations,
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

vi.mock("../../performance/PerformancePage", () => {
  // Counts module *evaluation*, not import resolution: a static import would
  // run this factory while the kernel graph loads, which is exactly the eager
  // chunk the lazy() boundary exists to keep out.
  kernelTestState.markPerformanceModuleEvaluated();

  return {
    PerformancePage: () => {
      if (!kernelTestState.isPerformanceReady()) {
        throw kernelTestState.pending;
      }

      return createElement("h1", null, "Trang hiệu suất");
    },
  };
});

import { AdminPerformanceRoute, RouteBoundary } from "./components";
import { contributions } from "./index";

// Captured at module load: the imports above have already evaluated the eager
// kernel graph, exactly as the app does at startup.
const eagerGraphPerformanceEvaluations =
  kernelTestState.performanceModuleEvaluations();

afterEach(async () => {
  await cleanup();
  kernelTestState.permissions = "admin";
  kernelTestState.isPending = false;
});

describe("kernel capability routes", () => {
  it("publishes every workspace destination in its sidebar section", () => {
    const destinations = Object.values(contributions)
      .filter((contribution) => contribution.kind === "navigation")
      .map((contribution) => {
        if (contribution.kind !== "navigation") {
          throw new Error("Expected navigation contribution");
        }
        return contribution.destination;
      });

    expect(
      destinations.map(({ id, to, section, roles }) => ({
        id,
        to,
        section,
        roles,
      })),
    ).toEqual([
      { id: "overview", to: "/", section: "operations", roles: undefined },
      {
        id: "messages",
        to: "/conversations",
        section: "operations",
        roles: undefined,
      },
      {
        id: "projects",
        to: "/projects",
        section: "operations",
        roles: undefined,
      },
      { id: "users", to: "/users", section: "team", roles: ["admin"] },
      {
        id: "settings",
        to: "/settings",
        section: "system",
        roles: ["admin"],
      },
      {
        id: "performance",
        to: "/hieu-suat",
        section: "system",
        roles: ["admin"],
      },
    ]);
  });

  it("keeps a recruiter's sidebar to the unguarded operations destinations", () => {
    const recruiterDestinations = Object.values(contributions)
      .filter((contribution) => contribution.kind === "navigation")
      .map((contribution) => contribution.destination)
      .filter(
        (destination) =>
          !destination.roles || destination.roles.includes("recruiter"),
      );

    expect(recruiterDestinations.map(({ id }) => id)).toEqual([
      "overview",
      "messages",
      "projects",
    ]);
    // The profile destination moved into the account menu, so no navigation
    // contribution may claim it any more.
    expect(contributions["kernel.navigation.account"]).toBeUndefined();
  });

  it("keeps the performance page module out of the eager kernel import graph", async () => {
    // `./index` is imported eagerly at module load, so this is the same load
    // the app pays for. It must not drag the performance chunk in.
    expect(eagerGraphPerformanceEvaluations).toBe(0);

    // The eager graph is live, not a stub: its boundary still renders.
    const eagerScreen = await render(
      createElement(
        RouteBoundary,
        null,
        createElement("p", null, "kernel graph ok"),
      ),
    );
    await expect
      .element(eagerScreen.getByText("kernel graph ok"))
      .toBeVisible();
    expect(kernelTestState.performanceModuleEvaluations()).toBe(0);

    // Non-vacuity guard: the counter has exactly one other way to move, and
    // the counter only proves something because rendering the deferred route
    // does move it.
    kernelTestState.resetPerformance();
    kernelTestState.releasePerformance();
    const deferredScreen = await render(createElement(AdminPerformanceRoute));
    await expect
      .element(deferredScreen.getByRole("heading", { name: "Trang hiệu suất" }))
      .toBeVisible();
    expect(kernelTestState.performanceModuleEvaluations()).toBe(1);
  });

  it("keeps a non-blank, announced loading state on the route boundary", async () => {
    const neverResolves = new Promise<never>(() => {});
    const screen = await render(
      createElement(
        RouteBoundary,
        null,
        createElement(() => {
          throw neverResolves;
        }),
      ),
    );

    const status = screen.getByRole("status");
    await expect.element(status).toBeVisible();
    await expect.element(status).toHaveTextContent("Đang tải trang...");

    // A blank or silent fallback leaves a screen reader with nothing while the
    // chunk downloads, so the text must be non-empty and the region live.
    expect(status.element().textContent?.trim()).not.toBe("");
    expect(status.element().getAttribute("aria-live")).toBe("polite");
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
