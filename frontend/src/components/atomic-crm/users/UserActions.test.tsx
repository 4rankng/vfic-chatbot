import { MemoryRouter } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
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
import "@/index.css";
import "./users.css";

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
  await page.viewport(1280, 900);
});

describe("account actions", () => {
  it.each([320, 390])(
    "keeps every mobile action target 44px and unboxed at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await mount();
      // All four actions are on the row itself — no overflow menu — so each one
      // is a real touch target.
      const actions = [
        screen.getByRole("link", {
          name: "Sửa Nguyễn Minh Anh",
          exact: true,
        }),
        screen.getByRole("button", {
          name: "Vô hiệu hóa Nguyễn Minh Anh",
          exact: true,
        }),
        screen.getByRole("button", {
          name: "Đổi mật khẩu Nguyễn Minh Anh",
          exact: true,
        }),
        screen.getByRole("button", {
          name: "Xóa vĩnh viễn Nguyễn Minh Anh",
          exact: true,
        }),
      ];
      for (const action of actions) {
        await expect.element(action).toBeVisible();
        const element = action.element();
        expect(element.getBoundingClientRect().width).toBeGreaterThanOrEqual(
          44,
        );
        expect(element.getBoundingClientRect().height).toBeGreaterThanOrEqual(
          44,
        );
        expect(getComputedStyle(element).borderTopWidth).toBe("0px");
        expect(getComputedStyle(element).backgroundColor).toBe(
          "rgba(0, 0, 0, 0)",
        );
      }
    },
  );

  it("locks a confirmed delete and explains its pending state", async () => {
    // `Promise.withResolvers` is ES2024 and the app's tsconfig lib is older.
    let finish!: (value: object) => void;
    mocks.remove.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const screen = await mount();
    await screen
      .getByRole("button", {
        name: "Xóa vĩnh viễn Nguyễn Minh Anh",
        exact: true,
      })
      .click();
    await screen
      .getByRole("button", { name: "Xóa vĩnh viễn", exact: true })
      .click();
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
      .getByRole("button", {
        name: "Đổi mật khẩu Nguyễn Minh Anh",
        exact: true,
      })
      .click();
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
