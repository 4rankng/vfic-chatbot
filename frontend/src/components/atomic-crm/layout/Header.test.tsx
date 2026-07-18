import { MemoryRouter } from "react-router";
import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/admin/user-menu", () => ({
  UserMenu: () => <div data-testid="user-menu" />,
}));

vi.mock("../installation/installation-context", () => ({
  useInstallationContext: () => ({
    manifest: {
      lifecycle: "ACTIVE",
      branding: { app_name: "Ting Ting" },
      customer_identity: { display_name: "VFIC" },
    },
  }),
}));

vi.mock("./topbar/useNotifications", () => ({
  useNotifications: () => ({ count: 0 }),
}));

import Header from "./Header";

describe("Header", () => {
  it("keeps the Ting Ting logo visible when the responsive layout hides the brand name", async () => {
    const screen = await render(
      <MemoryRouter>
        <Header />
      </MemoryRouter>,
    );

    const brand = screen.getByRole("link", { name: "Ting Ting" });
    await expect.element(brand).toBeVisible();
    expect(brand.element().querySelector("img")?.getAttribute("src")).toBe(
      "/ttsoft-logo.png",
    );
  });
});
