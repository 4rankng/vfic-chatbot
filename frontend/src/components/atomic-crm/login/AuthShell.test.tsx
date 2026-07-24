import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it } from "vitest";

import { AuthShell } from "./AuthShell";

afterEach(async () => {
  await cleanup();
});

describe("AuthShell", () => {
  it("renders the TingHire brand and project-owned recruiting artwork", async () => {
    const screen = await render(
      <AuthShell productName="TingHire">
        <h1>Đăng nhập</h1>
      </AuthShell>,
    );

    await expect
      .element(screen.getByText("TingHire", { exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("heading", { name: "Đăng nhập" }))
      .toBeVisible();
    expect(screen.container.querySelector("main.tt-hero")).not.toBeNull();
    expect(
      screen.container.querySelector('img[src="/brand/tinghire-icon-192.png"]'),
    ).not.toBeNull();
    expect(
      screen.container.querySelector(
        'img[src="/login-recruiting-console-v2.webp"]',
      ),
    ).not.toBeNull();
    expect(
      screen.container
        .querySelector('[data-slot="auth-frame"]')
        ?.classList.contains("lg:max-h-[820px]"),
    ).toBe(true);
    expect(screen.container.textContent).not.toContain("Thiết lập hệ thống");
  });
});
