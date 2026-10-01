import { MemoryRouter } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  remove: vi.fn(),
  reset: vi.fn(),
  notify: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("ra-core", () => ({
  useRecordContext: () => ({
    id: "user-1",
    full_name: "Nguyễn Minh Anh",
    email: "recruiter@vfic.dev",
    disabled: false,
  }),
  useCreatePath: () => () => "/users/user-1",
  useDataProvider: () => ({
    delete: mocks.remove,
    resetUserPassword: mocks.reset,
  }),
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));

import { UserActions } from "./UserActions";

const mount = () =>
  render(
    <MemoryRouter>
      <UserActions />
    </MemoryRouter>,
  );
beforeEach(() => {
  vi.resetAllMocks();
});
afterEach(async () => {
  await cleanup();
});

describe("account actions", () => {
  it("locks a confirmed delete and explains its pending state", async () => {
    let finish!: (value: object) => void;
    mocks.remove.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const screen = await mount();
    await screen
      .getByRole("button", { name: "Mở thao tác cho Nguyễn Minh Anh" })
      .click();
    await screen.getByRole("menuitem", { name: "Xóa vĩnh viễn" }).click();
    await screen.getByRole("button", { name: "Xóa vĩnh viễn" }).click();
    await expect.poll(() => mocks.remove.mock.calls.length).toBe(1);
    await expect
      .element(screen.getByRole("button", { name: "Đang xóa…" }))
      .toBeDisabled();
    await expect
      .element(screen.getByRole("button", { name: "Hủy" }))
      .toBeDisabled();
    finish({ data: {} });
    await expect.poll(() => mocks.refresh.mock.calls.length).toBe(1);
  });

  it("shows password rules inline and keeps secrets locked while resetting", async () => {
    let finish!: (value: object) => void;
    mocks.reset.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const screen = await mount();
    await screen
      .getByRole("button", { name: "Mở thao tác cho Nguyễn Minh Anh" })
      .click();
    await screen.getByRole("menuitem", { name: "Đổi mật khẩu" }).click();
    await screen.getByRole("button", { name: "Đặt mật khẩu" }).click();
    await expect
      .element(screen.getByText("Mật khẩu phải có ít nhất 8 ký tự."))
      .toBeVisible();
    expect(mocks.reset).not.toHaveBeenCalled();
    await screen.getByLabelText("Mật khẩu mới").fill("matkhau-moi");
    await screen.getByLabelText("Xác nhận mật khẩu").fill("matkhau-moi");
    await screen.getByRole("button", { name: "Đặt mật khẩu" }).click();
    await expect.poll(() => mocks.reset.mock.calls.length).toBe(1);
    await expect.element(screen.getByLabelText("Mật khẩu mới")).toBeDisabled();
    finish({});
    await expect.poll(() => mocks.refresh.mock.calls.length).toBe(1);
  });
});
