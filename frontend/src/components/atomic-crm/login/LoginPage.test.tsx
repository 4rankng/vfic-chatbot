import { TestMemoryRouter } from "ra-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
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
import "@/index.css";

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
  await page.viewport(1280, 900);
});

describe("LoginPage", () => {
  it.each([320, 390, 1280])(
    "uses compact auth fields and 13px labels on a mouse-operated viewport at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      expect(window.matchMedia("(pointer: fine)").matches).toBe(true);
      const screen = await renderLogin();
      for (const name of ["Email", "Mật khẩu"]) {
        const input = screen.getByRole("textbox", { name }).element();
        const wrapper = input.closest<HTMLElement>('[class~="group/input"]')!;
        expect(wrapper.getBoundingClientRect().height).toBe(
          width < 768 ? 40 : 36,
        );
        expect(getComputedStyle(input).fontSize).toBe("12px");
      }
      const labels = screen.container.querySelectorAll("label");
      for (const label of labels) {
        expect(getComputedStyle(label).fontSize).toBe("13px");
      }
      expect(
        screen
          .getByRole("button", { name: "Đăng nhập" })
          .element()
          .getBoundingClientRect().height,
      ).toBe(width < 768 ? 40 : 36);
    },
  );
  it.each([320, 390])(
    "keeps the password action unboxed with a44px phone target at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await renderLogin();
      const action = screen.getByRole("button", { name: "Hiện mật khẩu" });
      await expect.element(action).toBeVisible();
      const element = action.element();
      expect(element.getBoundingClientRect().width).toBeGreaterThanOrEqual(44);
      expect(element.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
      expect(getComputedStyle(element).borderTopWidth).toBe("0px");
      expect(getComputedStyle(element).backgroundColor).toBe(
        "rgba(0, 0, 0, 0)",
      );
      await action.click();
      await expect
        .element(screen.getByRole("textbox", { name: "Mật khẩu" }))
        .toHaveAttribute("type", "text");
    },
  );
  it("keeps credentials and offers an inline error when sign-in fails", async () => {
    mocks.login.mockRejectedValue(new Error("Email hoặc mật khẩu không đúng."));
    const screen = await renderLogin();
    await screen.getByRole("textbox", { name: "Email" }).fill("a@vfic.com.vn");
    await screen
      .getByRole("textbox", { name: "Mật khẩu" })
      .fill("mat-khau-2026");
    await screen.getByRole("button", { name: "Đăng nhập" }).click();
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Email hoặc mật khẩu không đúng.");
    await expect
      .element(screen.getByRole("textbox", { name: "Email" }))
      .toHaveValue("a@vfic.com.vn");
    await expect
      .element(screen.getByRole("button", { name: "Đăng nhập" }))
      .toBeEnabled();
  });

  it("explains malformed email before submitting credentials", async () => {
    const screen = await renderLogin();
    await screen
      .getByRole("textbox", { name: "Email" })
      .fill("khong-phai-email");
    await screen
      .getByRole("textbox", { name: "Mật khẩu" })
      .fill("mat-khau-2026");
    await screen.getByRole("button", { name: "Đăng nhập" }).click();
    await expect
      .element(screen.getByText("Nhập địa chỉ email hợp lệ."))
      .toBeVisible();
    expect(mocks.login).not.toHaveBeenCalled();
  });
  it("explains blank credentials inline and focuses the first invalid field", async () => {
    const screen = await renderLogin();

    await screen.getByRole("button", { name: "Đăng nhập" }).click();

    await expect
      .element(screen.getByText("Vui lòng nhập email."))
      .toBeVisible();
    await expect
      .element(screen.getByText("Vui lòng nhập mật khẩu."))
      .toBeVisible();
    const email = screen.getByRole("textbox", { name: /Email/ });
    await expect.element(email).toHaveAttribute("aria-invalid", "true");
    await expect.element(email).toHaveFocus();
    expect(email.element().getAttribute("aria-describedby")).toBeTruthy();
    expect(mocks.login).not.toHaveBeenCalled();
  });

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
