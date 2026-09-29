import { TestMemoryRouter } from "ra-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import type * as InstallationModule from "../installation/installation-context";
import type * as RaCoreModule from "ra-core";

import { TestMessages } from "../providers/commons/TestMessages";

/**
 * Sign-in form behaviour. Only the boundaries are stubbed: `useLogin` /
 * `useNotify`, the installation manifest and the admin toast. The field
 * composition (Untitled UI `TextField` / `Label` / `InputBase`), the reveal
 * control, the button and react-admin's own form engine are the real ones, so
 * the assertions are about what a recruiter gets: accessible names, the reveal
 * behaviour, and the exact credentials a submit hands to `login`.
 */

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("ra-core", async (importOriginal) => {
  const actual = await importOriginal<typeof RaCoreModule>();
  return {
    ...actual,
    useLogin: () => mocks.login,
    useNotify: () => mocks.notify,
  };
});

vi.mock("../installation/installation-context", async (importOriginal) => ({
  ...(await importOriginal<typeof InstallationModule>()),
  useInstallationContext: () => ({
    manifest: { lifecycle: "INACTIVE" },
    refreshRuntime: async () => {},
  }),
}));

vi.mock("@/components/admin/notification", () => ({
  Notification: () => null,
}));

import { LoginPage } from "./LoginPage";

const renderLogin = async () =>
  render(
    <TestMemoryRouter>
      <TestMessages>
        <LoginPage />
      </TestMessages>
    </TestMemoryRouter>,
  );

beforeEach(() => {
  mocks.login.mockReset();
  mocks.login.mockResolvedValue(undefined);
  mocks.notify.mockReset();
});

afterEach(async () => {
  await cleanup();
});

describe("LoginPage", () => {
  it("exposes both credentials under their Vietnamese names", async () => {
    const screen = await renderLogin();

    const email = screen.getByRole("textbox", { name: "Email" });
    const password = screen.getByRole("textbox", { name: "Mật khẩu" });

    await expect.element(email).toBeVisible();
    // The visual suite anchors the unauthenticated route on this input type.
    expect(email.element().getAttribute("type")).toBe("email");
    // `validationBehavior="aria"` keeps the native attribute off the input, so
    // react-admin's validator (not a browser bubble) owns the error.
    expect(email.element().getAttribute("aria-required")).toBe("true");
    expect(email.element().hasAttribute("required")).toBe(false);

    await expect.element(password).toBeVisible();
    expect(password.element().getAttribute("type")).toBe("password");

    await expect
      .element(screen.getByRole("button", { name: "Đăng nhập" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("link", { name: "Quên mật khẩu?" }))
      .toBeVisible();
  });

  it("reveals and re-hides the password from the console's own control", async () => {
    const screen = await renderLogin();
    const password = screen.getByRole("textbox", { name: "Mật khẩu" });

    await screen.getByRole("button", { name: "Hiện mật khẩu" }).click();
    expect(password.element().getAttribute("type")).toBe("text");
    await expect
      .element(screen.getByRole("button", { name: "Ẩn mật khẩu" }))
      .toBeVisible();

    await screen.getByRole("button", { name: "Ẩn mật khẩu" }).click();
    expect(password.element().getAttribute("type")).toBe("password");

    // The reveal control is the console's own, labelled in Vietnamese. The
    // library's English-labelled eye is suppressed on the field wrapper with
    // `[&>button]:hidden`; that suppression is a Tailwind utility, and this
    // vitest project deliberately does not emit the utility/`@theme` layer (see
    // the lane notes in performance-trend-layers.test.tsx), so it is only
    // observable in the app and e2e lanes — not asserted here.
  });

  it("submits the typed credentials through react-admin's login", async () => {
    const screen = await renderLogin();

    await screen.getByRole("textbox", { name: "Email" }).fill("a@vfic.com.vn");
    await screen
      .getByRole("textbox", { name: "Mật khẩu" })
      .fill("mat-khau-2026");
    await screen.getByRole("button", { name: "Đăng nhập" }).click();

    await expect.poll(() => mocks.login.mock.calls.length).toBe(1);
    expect(mocks.login).toHaveBeenCalledWith(
      { email: "a@vfic.com.vn", password: "mat-khau-2026" },
      undefined,
    );
  });
});
