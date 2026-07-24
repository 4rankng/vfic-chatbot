import { MemoryRouter } from "react-router";
import { render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mockUseNotifications } = vi.hoisted(() => ({
  mockUseNotifications: vi.fn(),
}));

vi.mock("@/components/admin/user-menu", () => ({
  UserMenu: () => <div data-testid="user-menu" />,
}));

vi.mock("./topbar/useNotifications", () => ({
  useNotifications: mockUseNotifications,
}));

vi.mock("./topbar/useNeedsAttention", () => ({
  useNeedsAttention: () => ({
    rows: [],
    total: 0,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

import Header, { WorkspaceSidebarBrand } from "./Header";

afterEach(() => {
  vi.clearAllMocks();
});

describe("Header", () => {
  it("renders only the compact TingHire mark in the icon rail", async () => {
    const screen = await render(
      <MemoryRouter>
        <WorkspaceSidebarBrand />
      </MemoryRouter>,
    );

    const brand = screen.getByRole("link", {
      name: "TingHire - về trang tổng quan",
    });
    await expect.element(brand).toBeVisible();

    const images = brand.element().querySelectorAll("img");
    expect(images).toHaveLength(1);
    expect(images[0]?.getAttribute("src")).toBe("/brand/tinghire-icon-192.png");
  });

  it("keeps the TingHire logo visible when the responsive layout hides the brand name", async () => {
    mockUseNotifications.mockReturnValue({ count: 0 });
    const screen = await render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );

    const brand = screen.getByRole("link", { name: "TingHire" });
    await expect.element(brand).toBeVisible();
    expect(brand.element().querySelector("img")?.getAttribute("src")).toBe(
      "/brand/tinghire-icon-192.png",
    );
  });

  it("opens the notifications popover when the bell is clicked", async () => {
    mockUseNotifications.mockReturnValue({ count: 2 });
    const screen = await render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );

    const bell = screen.getByRole("button", {
      name: "2 cuộc trò chuyện cần chú ý",
    });
    await expect.element(bell).toBeVisible();
    await bell.click();

    await expect
      .element(screen.getByRole("dialog", { name: "Thông báo" }))
      .toBeVisible();
  });

  it("does not mix DaisyUI navbar sizing into the workspace header", async () => {
    mockUseNotifications.mockReturnValue({ count: 0 });
    const screen = await render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );

    const header = screen.container.querySelector(".workspace-topbar");
    const actions = screen.container.querySelector(".workspace-topbar-actions");

    expect(header?.classList.contains("tt-navbar")).toBe(false);
    expect(actions?.classList.contains("tt-navbar-end")).toBe(false);
  });
});
