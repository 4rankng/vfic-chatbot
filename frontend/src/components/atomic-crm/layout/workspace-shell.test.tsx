import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Link,
  createHashRouter,
  RouterProvider,
  useLocation,
  type DataRouter,
} from "react-router";
import type { ReactNode } from "react";
import { memoryStore, StoreContextProvider } from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import "../conversations/inbox.css";

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
  ["Hiệu suất", "#/hieu-suat"],
];

let router: DataRouter | null = null;

/**
 * Mounts the real shell under the shipped hash router, so `useHref` resolves
 * the same `#/...` hrefs the browser does, with the real recruitment runtime.
 */
const renderWorkspaceShell = async (
  initialPath = "/conversations",
  content: ReactNode = <p>nội dung tuyển dụng</p>,
) => {
  window.location.hash = `#${initialPath}`;

  router = createHashRouter([
    {
      path: "*",
      element: (
        <RuntimeCapabilityProvider runtime={buildStaticRecruitmentRuntime(7)}>
          <TestMessages>
            <StoreContextProvider value={memoryStore()}>
              <WorkspaceShell>{content}</WorkspaceShell>
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

const InboxRouteFixture = () => {
  const location = useLocation();
  if (location.pathname !== "/conversations") {
    return <p>Trang dự án</p>;
  }
  const detailOpen = Boolean(new URLSearchParams(location.search).get("id"));
  return (
    <div
      className={`inbox-bg-container conversation-workspace ${detailOpen ? "conversation-open" : ""}`}
    >
      <div
        className={`app ${detailOpen ? "detail-open has-selected-conversation" : ""}`}
      >
        {detailOpen ? (
          <section className="center-panel">
            <Link to="/conversations" replace>
              Danh sách hội thoại
            </Link>
            <Link to="/conversations?id=candidate-1&panel=detail">
              Thông tin ứng viên
            </Link>
            <p>Hội thoại ứng viên</p>
          </section>
        ) : (
          <Link to="/conversations?id=candidate-1">Chọn ứng viên</Link>
        )}
      </div>
    </div>
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

describe("WorkspaceShell phone conversation chrome", () => {
  it("uses the full phone viewport in detail and restores navigation on Back and route history", async () => {
    await page.viewport(390, 844);
    const screen = await renderWorkspaceShell(
      "/conversations",
      <InboxRouteFixture />,
    );
    const topbar =
      screen.container.querySelector<HTMLElement>(".workspace-topbar")!;
    const main = screen.container.querySelector<HTMLElement>(
      ".workspace-frame-content",
    )!;
    // This lane does not compile Tailwind's hidden/lg:flex utilities. Match
    // the real phone rail visibility when measuring the vertical geometry.
    screen.container.querySelector<HTMLElement>(
      ".workspace-sidebar",
    )!.style.display = "none";
    screen.container.querySelector<HTMLElement>(
      ".workspace-frame > a",
    )!.style.cssText =
      "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)";
    await expect.element(topbar).toBeVisible();
    expect(topbar.getBoundingClientRect().height).toBe(56);

    await screen.getByRole("link", { name: "Chọn ứng viên" }).click();
    await expect.element(topbar).not.toBeVisible();
    const inbox = screen.container.querySelector<HTMLElement>(
      ".conversation-workspace",
    )!;
    expect(topbar.getBoundingClientRect().height).toBe(0);
    expect(main.getBoundingClientRect().top).toBe(0);
    expect(inbox.getBoundingClientRect().height).toBe(844);
    expect(inbox.getBoundingClientRect().bottom).toBe(844);

    await screen.getByRole("link", { name: "Thông tin ứng viên" }).click();
    await expect.element(topbar).not.toBeVisible();
    await screen.getByRole("link", { name: "Danh sách hội thoại" }).click();
    await expect.element(topbar).toBeVisible();
    expect(main.getBoundingClientRect().top).toBe(56);
    expect(inbox.getBoundingClientRect().height).toBe(788);

    await router!.navigate("/conversations?id=candidate-1");
    await expect.element(topbar).not.toBeVisible();
    await router!.navigate("/projects?id=project-1");
    await expect.element(topbar).toBeVisible();
    await router!.navigate(-1);
    await expect.element(topbar).not.toBeVisible();
    await router!.navigate(-1);
    await expect.element(topbar).toBeVisible();
  });

  it("hides the bar when opening a phone conversation deep link directly", async () => {
    await page.viewport(390, 844);
    const screen = await renderWorkspaceShell(
      "/conversations?id=candidate-1&panel=detail",
      <InboxRouteFixture />,
    );
    await expect
      .element(
        screen.container.querySelector<HTMLElement>(".workspace-topbar")!,
      )
      .not.toBeVisible();
    await screen.getByRole("link", { name: "Danh sách hội thoại" }).click();
    await expect
      .element(
        screen.container.querySelector<HTMLElement>(".workspace-topbar")!,
      )
      .toBeVisible();
  });

  it.each([768, 1024, 1440])(
    "preserves the topbar and content radius at %ipx",
    async (width) => {
      await page.viewport(width, 900);
      const screen = await renderWorkspaceShell(
        "/conversations",
        <InboxRouteFixture />,
      );
      const topbar =
        screen.container.querySelector<HTMLElement>(".workspace-topbar")!;
      const main = screen.container.querySelector<HTMLElement>(
        ".workspace-frame-content",
      )!;
      const before = {
        height: topbar.getBoundingClientRect().height,
        radius: getComputedStyle(main).borderTopLeftRadius,
      };
      await screen.getByRole("link", { name: "Chọn ứng viên" }).click();
      await expect.element(topbar).toBeVisible();
      expect(topbar.getBoundingClientRect().height).toBe(before.height);
      expect(getComputedStyle(main).borderTopLeftRadius).toBe(before.radius);
    },
  );
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
  it("opens the command palette without the browser shortcut and renders hash destinations", async () => {
    const screen = await renderWorkspaceShell("/conversations");
    const shortcut = new KeyboardEvent("keydown", {
      key: "k",
      code: "KeyK",
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.body.dispatchEvent(shortcut);

    const dialog = screen.getByRole("dialog");
    await expect.element(dialog).toBeVisible();
    expect(shortcut.defaultPrevented).toBe(true);
    const project = dialog.getByRole("option", { name: "Dự án", exact: true });
    expect(project.element().getAttribute("href")).toBe("#/projects");
    await project.click();
    await expect.poll(() => window.location.hash).toBe("#/projects");
    await expect.element(dialog).not.toBeInTheDocument();

    document.body.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "k",
        code: "KeyK",
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
      }),
    );
    const reopened = screen.getByRole("dialog");
    await expect.element(reopened).toBeVisible();
    await reopened.getByRole("option", { name: "Dự án", exact: true }).click();
    await expect.element(reopened).not.toBeInTheDocument();
  });

  it("moves skip-navigation focus to the workspace without replacing the hash route", async () => {
    const screen = await renderWorkspaceShell("/projects");
    const before = window.location.hash;

    await screen.getByRole("link", { name: "Bỏ qua điều hướng" }).click();

    expect(window.location.hash).toBe(before);
    expect(document.activeElement).toBe(
      screen.container.querySelector("#main-content"),
    );
  });

  it("keeps long tablet pages reachable through the document scroll owner", async () => {
    await page.viewport(900, 650);
    const screen = await renderWorkspaceShell("/users");
    const main = screen.container.querySelector<HTMLElement>("#main-content")!;
    main.firstElementChild!.setAttribute("style", "height: 1400px");

    expect(getComputedStyle(document.body).overflowY).not.toBe("hidden");
    expect(
      getComputedStyle(document.getElementById("root") ?? document.body)
        .overflowY,
    ).not.toBe("hidden");
    expect(getComputedStyle(main).overflowY).toBe("visible");
  });

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
