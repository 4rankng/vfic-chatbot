import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createHashRouter,
  RouterProvider,
  useLocation,
} from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import { RuntimeCapabilityProvider } from "../RuntimeCapabilityProvider";
import { buildStaticRecruitmentRuntime } from "../static-recruitment-runtime";
import { WorkspaceShell } from "../../layout/workspace-shell";

const roleActionsState = vi.hoisted(() => ({
  isAdmin: true,
}));

vi.mock("../../hooks/useRoleActions", () => ({
  useRoleActions: () => ({
    isAdmin: roleActionsState.isAdmin,
    canEdit: true,
  }),
}));

vi.mock("../../layout/topbar/useNotifications", () => ({
  useNotifications: () => ({ count: 0 }),
}));

const LocationProbe = () => {
  const location = useLocation();

  return (
    <output data-testid="location-probe">
      {`${location.pathname}${location.search}`}
    </output>
  );
};

const routerDisposers: Array<() => void> = [];

const renderWorkspaceShell = async (initialPath = "/") => {
  window.location.hash = `#${initialPath}`;
  const router = createHashRouter([
    {
      path: "*",
      element: (
        <RuntimeCapabilityProvider runtime={buildStaticRecruitmentRuntime(7)}>
          <WorkspaceShell>
            <LocationProbe />
          </WorkspaceShell>
        </RuntimeCapabilityProvider>
      ),
    },
  ]);

  routerDisposers.push(() => router.dispose());

  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
};

afterEach(async () => {
  await cleanup();
  routerDisposers.splice(0).forEach((dispose) => dispose());
  window.location.hash = "#/";
  await page.viewport(1280, 720);
  roleActionsState.isAdmin = true;
});

const ADMIN_SECTION_HEADINGS = [
  "Vận hành",
  "Kiến thức",
  "Đội ngũ & Agent",
  "Hệ thống",
];

const ADMIN_DESTINATIONS = [
  "Tổng quan",
  "Tin nhắn",
  "Dự án",
  "Nguồn kiến thức",
  "Cơ sở kiến thức",
  "Agent",
  "Người dùng",
  "Cài đặt",
  "Nhật ký bot",
  "Hiệu suất",
];

describe("kernel mobile navigation drawer", () => {
  it("hides the desktop sidebar at a phone viewport", async () => {
    await page.viewport(390, 844);

    const screen = await renderWorkspaceShell("/");
    const sidebar = screen.container.querySelector<HTMLElement>("aside");

    expect(sidebar).toBeInstanceOf(HTMLElement);
    expect(getComputedStyle(sidebar as HTMLElement).display).toBe("none");

    // The phone affordance replaces it, and nothing is open yet.
    await expect
      .element(screen.getByRole("button", { name: "Mở điều hướng" }))
      .toBeVisible();
    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the drawer with every admin section and destination", async () => {
    await page.viewport(390, 844);

    const screen = await renderWorkspaceShell("/");

    await screen.getByRole("button", { name: "Mở điều hướng" }).click();

    const drawer = screen.getByRole("dialog");
    await expect.element(drawer).toBeVisible();

    for (const heading of ADMIN_SECTION_HEADINGS) {
      await expect
        .element(drawer.getByText(heading, { exact: true }))
        .toBeVisible();
    }

    for (const label of ADMIN_DESTINATIONS) {
      await expect
        .element(drawer.getByRole("link", { name: label }))
        .toBeVisible();
    }
  });

  it("keeps a recruiter out of the admin-only drawer destinations", async () => {
    await page.viewport(390, 844);
    roleActionsState.isAdmin = false;

    const screen = await renderWorkspaceShell("/");

    await screen.getByRole("button", { name: "Mở điều hướng" }).click();

    const drawer = screen.getByRole("dialog");
    await expect.element(drawer).toBeVisible();

    for (const label of ["Tổng quan", "Tin nhắn", "Dự án"]) {
      await expect
        .element(drawer.getByRole("link", { name: label }))
        .toBeVisible();
    }

    await expect
      .element(drawer.getByRole("link", { name: "Người dùng" }))
      .not.toBeInTheDocument();
    await expect
      .element(drawer.getByRole("link", { name: "Nguồn kiến thức" }))
      .not.toBeInTheDocument();
    await expect
      .element(drawer.getByText("Hệ thống", { exact: true }))
      .not.toBeInTheDocument();
  });

  it("closes the drawer and navigates when a destination is activated", async () => {
    await page.viewport(390, 844);

    const screen = await renderWorkspaceShell("/");

    await screen.getByRole("button", { name: "Mở điều hướng" }).click();
    await expect.element(screen.getByRole("dialog")).toBeVisible();

    await screen
      .getByRole("dialog")
      .getByRole("link", { name: "Người dùng" })
      .click();

    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();
    await expect
      .element(screen.getByTestId("location-probe"))
      .toHaveTextContent("/users");
  });

  it("keeps the sectioned sidebar navigation on desktop", async () => {
    await page.viewport(1280, 720);

    const screen = await renderWorkspaceShell("/");
    const sidebar = screen.container.querySelector<HTMLElement>("aside");

    expect(getComputedStyle(sidebar as HTMLElement).display).not.toBe("none");
    await expect
      .element(screen.getByRole("link", { name: "Hiệu suất" }))
      .toBeVisible();
    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();
  });
});
