import { type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UserAccount } from "../types";
import "@/index.css";
import "./users.css";

const { accounts, secondAccount, listState } = vi.hoisted(() => {
  const first: UserAccount = {
    id: "user-1",
    email: "recruiter@vfic.dev",
    full_name: "Nguyễn Minh Anh",
    role: "recruiter",
    disabled: false,
    created_at: "2026-07-22T10:00:00Z",
    updated_at: "2026-07-22T10:00:00Z",
  };
  const second: UserAccount = {
    id: "user-2",
    email: "admin@vfic.dev",
    full_name: "Trần Quốc Bảo",
    role: "admin",
    disabled: true,
    created_at: "2026-06-02T10:00:00Z",
    updated_at: "2026-06-02T10:00:00Z",
  };
  const accounts = [first];
  return {
    accounts,
    secondAccount: second,
    listState: {
      data: accounts as UserAccount[],
      isPending: false,
      total: accounts.length,
      page: 1,
      perPage: 25,
      setPage: () => {},
      setPerPage: () => {},
      hasNextPage: false,
      hasPreviousPage: false,
    },
  };
});

// `UserList` composes the kit's `ListTable`; what matters here is what a
// recruiter sees — the directory's columns, rows, row action and empty state —
// not which class names carry it. The kit's own suite covers the real
// react-admin list context, so this file stubs the context hooks it renders
// against.
vi.mock("ra-core", () => ({
  ListBase: ({ children }: { children: ReactNode }) => children,
  useCreatePath: () => (options: { type: string }) => `/users/${options.type}`,
  // The kit's index re-exports the form controls, so their hooks have to exist
  // even though this page renders none of them.
  useInput: () => ({}),
  useDataProvider: () => ({
    enableUser: vi.fn(),
    disableUser: vi.fn(),
    resetUserPassword: vi.fn(),
    delete: vi.fn(),
  }),
  useListContext: () => listState,
  useListPaginationContext: () => listState,
  useNotify: () => vi.fn(),
  usePermissions: () => ({ permissions: "admin", isPending: false }),
  useRecordContext: () => listState.data[0],
  useRefresh: () => vi.fn(),
  useTranslate: () => (key: string, options?: { smart_count?: number }) =>
    key === "resources.users.name" && options?.smart_count ? "Tài khoản" : key,
}));

import { UserList } from "./UserList";

const mountList = () => (
  <MemoryRouter>
    <UserList />
  </MemoryRouter>
);

afterEach(async () => {
  listState.data = accounts;
  listState.total = accounts.length;
  await cleanup();
  await page.viewport(1280, 720);
});

describe("UserList", () => {
  it("renders the directory as one labelled table with a count line", async () => {
    listState.data = [...accounts, secondAccount];
    listState.total = 2;
    const screen = await render(mountList());

    await expect
      .element(screen.getByRole("grid", { name: "Danh sách tài khoản" }))
      .toBeVisible();

    const headers = Array.from(
      screen.container.querySelectorAll('[role="columnheader"]'),
    ).map((node) => node.textContent);
    expect(headers).toEqual([
      "Ảnh đại diện",
      "Người dùng",
      "Vai trò",
      "Trạng thái",
      "Ngày tạo",
      "Thao tác",
    ]);

    expect(screen.container.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(screen.container.textContent).toContain("2 tài khoản");
    await expect.element(screen.getByText("Nguyễn Minh Anh")).toBeVisible();
    await expect.element(screen.getByText("recruiter@vfic.dev")).toBeVisible();
    // The avatar cell is Untitled UI's `Avatar`, fed the record's initials: the
    // first and last words of a Vietnamese name.
    const avatars = Array.from(
      screen.container.querySelectorAll(".user-directory-cell-avatar"),
    );
    expect(avatars.map((cell) => cell.textContent?.trim())).toEqual(["NA", "TB"]);
    expect(avatars[0]?.querySelector("img")).toBeNull();
  });

  it("names each account's row action and keeps create reachable", async () => {
    const screen = await render(mountList());
    await expect
      .element(
        screen.getByRole("button", {
          name: "Mở thao tác cho Nguyễn Minh Anh",
        }),
      )
      .toBeVisible();

    const create = screen.getByRole("link", { name: "Tạo tài khoản" });
    await expect.element(create).toBeVisible();
    expect(create.element().getAttribute("href")).toContain("/users/create");
  });

  it("shows the kit empty state when there is no account", async () => {
    listState.data = [];
    listState.total = 0;
    const screen = await render(mountList());

    await expect
      .element(screen.getByText("Chưa có tài khoản nào"))
      .toBeVisible();
    await expect
      .element(
        screen.getByText("Tạo tài khoản để phân quyền cho đội tuyển dụng."),
      )
      .toBeVisible();
    expect(screen.container.querySelector("table")).toBeNull();
  });
});
