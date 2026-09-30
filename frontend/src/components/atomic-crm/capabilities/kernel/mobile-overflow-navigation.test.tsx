import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createHashRouter, RouterProvider, useLocation } from "react-router";
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
  // The console runs on react-admin's hash router, so the shell's
  // `useHref` links are hash hrefs here too and a click navigates in place.
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

const ADMIN_SECTION_HEADINGS = ["Vận hành", "Đội ngũ & Agent", "Hệ thống"];

const ADMIN_NAV_HREFS = [
  "#/",
  "#/conversations",
  "#/projects",
  "#/personas",
  "#/users",
  "#/settings",
  "#/bot_runs",
  "#/hieu-suat",
];

const ADMIN_DESTINATION_LABELS = [
  "Tổng quan",
  "Tin nhắn",
  "Dự án",
  "Agent",
  "Người dùng",
  "Cài đặt",
  "Nhật ký bot",
  "Hiệu suất",
];

describe("kernel mobile navigation drawer", () => {
  it("hands phone widths a drawer affordance instead of the desktop sidebar", async () => {
    await page.viewport(390, 844);

    const screen = await renderWorkspaceShell("/");
    const sidebar = screen.container.querySelector<HTMLElement>("aside");

    expect(sidebar).toBeInstanceOf(HTMLElement);
    // Tailwind utilities are not compiled inside the Vitest browser project,
    // so the breakpoint contract is checked as the classes the shell ships:
    // the sidebar exists below `lg` only as a hidden node, and the trigger
    // disappears from `lg` up.
    expect(sidebar?.classList.contains("hidden")).toBe(true);
    expect(sidebar?.classList.contains("lg:flex")).toBe(true);

    const trigger = screen.getByRole("button", { name: "Mở điều hướng" });
    await expect.element(trigger).toBeVisible();
    expect(trigger.element().classList.contains("lg:hidden")).toBe(true);
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

    for (const label of ADMIN_DESTINATION_LABELS) {
      await expect
        .element(drawer.getByRole("link", { name: label, exact: true }))
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
        .element(drawer.getByRole("link", { name: label, exact: true }))
        .toBeVisible();
    }

    await expect
      .element(drawer.getByRole("link", { name: "Người dùng", exact: true }))
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
      .getByRole("link", { name: "Người dùng", exact: true })
      .click();

    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();
    await expect
      .element(screen.getByTestId("location-probe"))
      .toHaveTextContent("/users");
  });

  it("keeps the icon-first rail navigation available on desktop", async () => {
    await page.viewport(1280, 720);

    const screen = await renderWorkspaceShell("/");
    const sidebar = screen.container.querySelector<HTMLElement>("aside")!;

    expect(sidebar.classList.contains("lg:flex")).toBe(true);
    // The rail is icon-first: every destination is reachable, each label lives
    // in an sr-only span (plus a hover tooltip), and the section headings belong
    // to the drawer, not to the rail.
    expect(
      [...sidebar.querySelectorAll("nav p")].map((heading) =>
        heading.textContent?.trim(),
      ),
    ).toEqual([]);
    expect(
      [...sidebar.querySelectorAll("nav a[href]")].map((link) =>
        link.getAttribute("href"),
      ),
    ).toEqual(ADMIN_NAV_HREFS);
    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();
  });
});
