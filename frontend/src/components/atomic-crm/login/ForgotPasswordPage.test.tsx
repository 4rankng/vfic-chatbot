import { TestMemoryRouter } from "ra-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import type * as InstallationModule from "../installation/installation-context";
import type * as RaCoreModule from "ra-core";

import { TestMessages } from "../providers/commons/TestMessages";

/**
 * Recovery-flow behaviour. The password service is stubbed (the same seam
 * `useResendCooldown.test` uses) and the toast and manifest are stubbed; the two
 * steps, the fields, the buttons and the resend cooldown hook are the real ones,
 * so the assertions cover the accessible names, the step transition and the
 * Vietnamese validation messages.
 */

const mocks = vi.hoisted(() => ({
  requestPasswordResetOtp: vi.fn(),
  resetPasswordWithOtp: vi.fn(),
  notify: vi.fn(),
}));

vi.mock("ra-core", async (importOriginal) => {
  const actual = await importOriginal<typeof RaCoreModule>();
  return { ...actual, useNotify: () => mocks.notify };
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

vi.mock("./passwordRecoveryService", () => ({
  requestPasswordResetOtp: mocks.requestPasswordResetOtp,
  resetPasswordWithOtp: mocks.resetPasswordWithOtp,
}));

import { ForgotPasswordPage } from "./ForgotPasswordPage";

const renderRecovery = async () =>
  render(
    <TestMemoryRouter>
      <TestMessages>
        <ForgotPasswordPage />
      </TestMessages>
    </TestMemoryRouter>,
  );

beforeEach(() => {
  mocks.requestPasswordResetOtp.mockReset();
  mocks.requestPasswordResetOtp.mockResolvedValue(undefined);
  mocks.resetPasswordWithOtp.mockReset();
  mocks.resetPasswordWithOtp.mockResolvedValue(undefined);
  mocks.notify.mockReset();
});

afterEach(async () => {
  await cleanup();
});

describe("ForgotPasswordPage", () => {
  it("asks for the account email first", async () => {
    const screen = await renderRecovery();

    await expect
      .element(screen.getByRole("heading", { name: "Khôi phục mật khẩu" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("textbox", { name: "Email" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Gửi mã OTP" }))
      .toBeVisible();
    expect(screen.container.querySelectorAll("input")).toHaveLength(1);
  });

  it("moves to the OTP step and requests the code for the normalised email", async () => {
    const screen = await renderRecovery();

    await screen
      .getByRole("textbox", { name: "Email" })
      .fill("Recruiter@VFIC.com.vn ");
    await screen.getByRole("button", { name: "Gửi mã OTP" }).click();

    await expect
      .poll(() => mocks.requestPasswordResetOtp.mock.calls.length)
      .toBe(1);
    expect(mocks.requestPasswordResetOtp).toHaveBeenCalledWith(
      "recruiter@vfic.com.vn",
    );

    for (const name of [
      /^Email/,
      /Mã OTP/,
      /Mật khẩu mới/,
      /Xác nhận mật khẩu/,
    ]) {
      await expect.element(screen.getByRole("textbox", { name })).toBeVisible();
    }
    await expect
      .element(screen.getByRole("button", { name: "Đổi mật khẩu" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: /Gửi lại mã/ }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("link", { name: "Quay lại đăng nhập" }))
      .toBeVisible();
  });

  it("refuses a mismatched confirmation without calling the reset service", async () => {
    const screen = await renderRecovery();

    await screen.getByRole("textbox", { name: "Email" }).fill("a@vfic.com.vn");
    await screen.getByRole("button", { name: "Gửi mã OTP" }).click();
    await expect
      .poll(() => screen.container.querySelectorAll("input").length)
      .toBe(4);

    await screen.getByRole("textbox", { name: /Mã OTP/ }).fill("123456");
    await screen.getByLabelText(/Mật khẩu mới/).fill("mat-khau-2026");
    await screen.getByLabelText(/Xác nhận mật khẩu/).fill("khac-mat-khau");
    await screen.getByRole("button", { name: "Đổi mật khẩu" }).click();

    await expect.poll(() => mocks.notify.mock.calls.length).toBeGreaterThan(0);
    expect(mocks.notify).toHaveBeenCalledWith("Mật khẩu xác nhận không khớp.", {
      type: "error",
    });
    expect(mocks.resetPasswordWithOtp).not.toHaveBeenCalled();
  });
});
