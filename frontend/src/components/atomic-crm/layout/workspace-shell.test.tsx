import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createHashRouter,
  RouterProvider,
  type DataRouter,
} from "react-router";
import { memoryStore, StoreContextProvider } from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";

import { RuntimeCapabilityProvider } from "../capabilities/RuntimeCapabilityProvider";
import { buildStaticRecruitmentRuntime } from "../capabilities/static-recruitment-runtime";
import { TestMessages } from "../providers/commons/TestMessages";
import { WorkspaceShell } from "./workspace-shell";

// The attention count the topbar poller reports. Only the notification control
// and the inbox badge read it; `0` unless a test says otherwise.
const attention = vi.hoisted(() => ({ count: 0 }));

vi.mock("../hooks/useRoleActions", () => ({
  useRoleActions: () => ({ isAdmin: true, canEdit: true }),
}));

vi.mock("./topbar/useNotifications", () => ({
  useNotifications: () => ({ count: attention.count }),
}));

// The panel query stays out of this suite: the shell only wires the hook up.
// Rendering the rows it returns is covered by notifications-menu.test.tsx.
vi.mock("./topbar/useNeedsAttention", () => ({
  useNeedsAttention: () => ({
    rows: [],
    total: 0,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

// The account menu owns the ra-core auth/identity stack and is not the subject
// here; the deleted Header.test.tsx stubbed its user menu for the same reason.
vi.mock("./topbar/account-menu", () => ({
  AccountMenu: () => <div data-testid="account-menu" />,
}));

const ADMIN_SECTION_HEADINGS = ["Vận hành", "Đội ngũ", "Hệ thống"];

/** Every admin destination, in the order the navigation renders it. */
const ADMIN_DESTINATIONS: readonly (readonly [string, string])[] = [
  ["Tổng quan", "#/"],
  ["Tin nhắn", "#/conversations"],
  ["Dự án", "#/projects"],
  ["Người dùng", "#/users"],
  ["Cài đặt", "#/settings"],
  ["Nhật ký bot", "#/bot_runs"],
  ["Hiệu suất", "#/hieu-suat"],
];

let router: DataRouter | null = null;

/**
 * Mounts the real shell under the shipped hash router, so `useHref` resolves
 * the same `#/...` hrefs the browser does, with the real recruitment runtime.
 */
const renderWorkspaceShell = async (initialPath = "/conversations") => {
  window.location.hash = `#${initialPath}`;

  router = createHashRouter([
    {
      path: "*",
      element: (
        <RuntimeCapabilityProvider runtime={buildStaticRecruitmentRuntime(7)}>
          <TestMessages>
            <StoreContextProvider value={memoryStore()}>
              <WorkspaceShell>
                <p>nội dung tuyển dụng</p>
              </WorkspaceShell>
            </StoreContextProvider>
          </TestMessages>
        </RuntimeCapabilityProvider>
      ),
    },
  ]);

  return render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
};

afterEach(async () => {
  await cleanup();
  router?.dispose();
  router = null;
  window.location.hash = "#/";
  attention.count = 0;
  await page.viewport(1440, 900);
});

describe("WorkspaceShell desktop rail", () => {
  it("starts as an icon-first rail whose links name their destination in a hash href", async () => {
    await page.viewport(1440, 900);

    const screen = await renderWorkspaceShell("/conversations");

    const rail = screen.container.querySelector<HTMLElement>(
      "aside.workspace-sidebar",
    );
    expect(rail).toBeInstanceOf(HTMLElement);
    await expect.element(rail!).toBeVisible();

    for (const [label, href] of ADMIN_DESTINATIONS) {
      const link = page.getByRole("link", { name: label, exact: true });
      await expect.element(link).toBeVisible();
      expect(link.element().getAttribute("href")).toBe(href);
      // Collapsed: the console look keeps the label for assistive tech only.
      expect(
        link.element().querySelector<HTMLElement>("span.sr-only")?.textContent,
      ).toBe(label);
    }

    // No section headings until the rail is expanded.
    for (const heading of ADMIN_SECTION_HEADINGS) {
      await expect
        .element(page.getByText(heading, { exact: true }))
        .not.toBeInTheDocument();
    }

    // One route, one current link — the sidebar badge never marks a section.
    const current = [
      ...rail!.querySelectorAll<HTMLAnchorElement>('a[aria-current="page"]'),
    ];
    expect(
      current.map(
        (anchor) => anchor.querySelector("span.sr-only")?.textContent,
      ),
    ).toEqual(["Tin nhắn"]);
    expect(current[0].getAttribute("href")).toBe("#/conversations");
  });
});

describe("WorkspaceShell phone drawer", () => {
  it("hides the rail and reaches the same destinations through the drawer", async () => {
    await page.viewport(390, 844);

    const screen = await renderWorkspaceShell("/conversations");

    const rail = screen.container.querySelector<HTMLElement>(
      "aside.workspace-sidebar",
    );
    expect(rail).toBeInstanceOf(HTMLElement);
    // `lg:` is not evaluated in this project (the vitest config runs the React
    // plugin only, so no Tailwind utilities are generated); the phone layout is
    // asserted through the hide-below-lg class contract plus the drawer below.
    expect(rail!.classList.contains("hidden")).toBe(true);
    expect(rail!.classList.contains("lg:flex")).toBe(true);
    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: "Mở điều hướng" });
    await expect.element(trigger).toBeVisible();
    expect(trigger.element().classList.contains("lg:hidden")).toBe(true);
    await trigger.click();

    const drawer = screen.getByRole("dialog");
    await expect.element(drawer).toBeVisible();

    // The drawer is always labelled, so headings and text labels are readable.
    for (const heading of ADMIN_SECTION_HEADINGS) {
      await expect
        .element(drawer.getByText(heading, { exact: true }))
        .toBeVisible();
    }

    for (const [label, href] of ADMIN_DESTINATIONS) {
      const link = drawer.getByRole("link", { name: label, exact: true });
      await expect.element(link).toBeVisible();
      expect(link.element().getAttribute("href")).toBe(href);
    }

    await drawer.getByRole("link", { name: "Dự án", exact: true }).click();

    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();
    await expect
      .poll(() =>
        [
          ...(rail?.querySelectorAll<HTMLAnchorElement>(
            'a[aria-current="page"]',
          ) ?? []),
        ].map((anchor) => anchor.querySelector("span.sr-only")?.textContent),
      )
      .toEqual(["Dự án"]);
  });

  // The drawer used to carry its width on the inner Dialog while the panel
  // stayed `w-full`, so the panel box was wider than the visible surface: a
  // strip of scrim showed beside the drawer and the slide-in animation moved
  // a box wider than anything painted. These are class contracts because this
  // project generates no Tailwind utilities (see the note above).
  it("sizes the sliding panel, not the dialog inside it", async () => {
    await page.viewport(390, 844);

    const screen = await renderWorkspaceShell("/conversations");
    await screen.getByRole("button", { name: "Mở điều hướng" }).click();

    const drawer = screen.getByRole("dialog");
    await expect.element(drawer).toBeVisible();

    const panel = drawer.element().parentElement;
    expect(panel).not.toBeNull();
    expect(panel!.className).toContain("w-72");
    expect(panel!.className).toContain("max-w-[85vw]");
    // The dialog fills the panel instead of re-declaring a narrower width.
    expect(drawer.element().className).not.toMatch(/(^|\s)w-72(\s|$)/);
  });
});

describe("WorkspaceShell topbar", () => {
  it("names the notifications control after the attention count", async () => {
    await page.viewport(1440, 900);
    attention.count = 3;

    await renderWorkspaceShell("/conversations");

    await expect
      .element(
        page.getByRole("button", {
          name: "3 cuộc trò chuyện cần chú ý",
          exact: true,
        }),
      )
      .toBeVisible();

    // The badge-bearing link and the bell describe the same queue.
    expect(
      page
        .getByRole("link", { name: "Tin nhắn", exact: true })
        .element()
        .getAttribute("href"),
    ).toBe("#/conversations?needs_attention=true");
  });

  it("names the notifications control with the idle copy when nothing is waiting", async () => {
    await page.viewport(1440, 900);

    await renderWorkspaceShell("/conversations");

    await expect
      .element(
        page.getByRole("button", {
          name: "Không có thông báo mới",
          exact: true,
        }),
      )
      .toBeVisible();
  });
});
