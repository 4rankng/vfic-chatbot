import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import { RuntimeCapabilityProvider } from "../runtime-context";
import { buildStaticRecruitmentRuntime } from "../static-recruitment-runtime";
import { WorkspaceFrame } from "../../layout/workspace-frame";

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

vi.mock("../../layout/Header", () => ({
  __esModule: true,
  default: () => <header className="workspace-topbar" />,
  WorkspaceSidebarBrand: () => (
    <a
      className="workspace-sidebar-brand"
      href="#/"
      aria-label="TingHire - về trang tổng quan"
    >
      <span className="workspace-sidebar-brand-mark" aria-hidden="true" />
    </a>
  ),
}));

const LocationProbe = () => {
  const location = useLocation();

  return (
    <output data-testid="location-probe">
      {`${location.pathname}${location.search}`}
    </output>
  );
};

const renderWorkspaceFrame = async (initialPath = "/") =>
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <RuntimeCapabilityProvider runtime={buildStaticRecruitmentRuntime(7)}>
        <WorkspaceFrame>
          <LocationProbe />
        </WorkspaceFrame>
      </RuntimeCapabilityProvider>
    </MemoryRouter>,
  );

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 720);
  roleActionsState.isAdmin = true;
});

describe("kernel mobile overflow navigation", () => {
  it("keeps the admin primary dock to exactly five controls at 320px without wrapping or horizontal overflow", async () => {
    await page.viewport(320, 844);
    await document.fonts.ready;

    const screen = await renderWorkspaceFrame("/");
    const navigation = screen.container.querySelector<HTMLElement>(
      ".workspace-navigation-mobile",
    )!;
    const items = navigation.querySelector<HTMLElement>(
      ".workspace-navigation-items",
    )!;
    const links = navigation.querySelectorAll<HTMLElement>(
      ".workspace-navigation-link",
    );

    expect(
      Array.from(links, (link) =>
        link.querySelector(".workspace-navigation-label")?.textContent?.trim(),
      ),
    ).toEqual(["Tổng quan", "Tin nhắn", "Dự án", "Cài đặt", "Thêm"]);
    expect(links).toHaveLength(5);
    expect(items.scrollWidth).toBeLessThanOrEqual(items.clientWidth + 1);
    expect(navigation.scrollWidth).toBeLessThanOrEqual(
      navigation.clientWidth + 1,
    );

    const firstTop = links[0]?.getBoundingClientRect().top ?? 0;
    links.forEach((link) => {
      const linkRect = link.getBoundingClientRect();

      expect(linkRect.top).toBeCloseTo(firstTop, 0);
      expect(linkRect.left).toBeGreaterThanOrEqual(-0.5);
      expect(linkRect.right).toBeLessThanOrEqual(window.innerWidth + 0.5);
    });
  });

  it("keeps Performance reachable from the mobile More menu at 320px", async () => {
    await page.viewport(320, 844);

    const screen = await renderWorkspaceFrame("/");

    await screen
      .getByRole("button", { name: "Mở thêm mục điều hướng" })
      .click();

    const performanceLink = screen.getByRole("link", { name: "Hiệu suất" });
    await expect.element(performanceLink).toBeVisible();
    await expect
      .element(screen.getByRole("link", { name: "Tài khoản" }))
      .toBeVisible();

    await performanceLink.click();

    await expect
      .element(screen.getByTestId("location-probe"))
      .toHaveTextContent("/hieu-suat");
  });

  it("keeps the desktop rail navigation available for administrators", async () => {
    await page.viewport(1280, 720);

    const screen = await renderWorkspaceFrame("/");
    const rail = screen.container.querySelector<HTMLElement>(
      ".workspace-navigation-rail",
    )!;

    await expect
      .element(screen.getByRole("link", { name: "Hiệu suất" }))
      .toBeVisible();
    expect(
      rail.querySelector('.workspace-navigation-link[href="/hieu-suat"]'),
    ).not.toBeNull();
  });
});
