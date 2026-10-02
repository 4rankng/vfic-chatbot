import { type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as RaCoreModule from "ra-core";

import type { UserAccount } from "../types";
import "@/index.css";
import "./users.css";
import "../conversations/inbox.css";
import "../integrations/settings.css";

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
// react-admin list context, so this file stubs the list hooks the page reads.
// `useRecordContext` is deliberately NOT stubbed: the badges and row actions
// render from the record context `ListTable` provides per row, and stubbing it
// once masked a regression where the context was missing entirely (the columns
// rendered null in production while the tests stayed green).
vi.mock("ra-core", async (importOriginal) => ({
  ...(await importOriginal<typeof RaCoreModule>()),
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
  useRefresh: () => vi.fn(),
  useTranslate: () => (key: string, options?: { smart_count?: number }) =>
    key === "resources.users.name" && options?.smart_count ? "Tài khoản" : key,
}));

import { UserList } from "./UserList";
import { SettingsChrome } from "../integrations/SettingsChrome";

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
  it.each([320, 360, 390])(
    "keeps embedded mobile account metadata separate and inside the card at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      listState.data = [
        {
          ...accounts[0],
          email: "nguyen.minh.anh.recruitment@vfic.example.org",
        },
      ];
      const screen = await render(
        <MemoryRouter>
          <SettingsChrome activeItemId="settings-users" onItemSelect={() => {}}>
            <div className="settings-embedded-resource settings-embedded-users">
              <UserList embedded />
            </div>
          </SettingsChrome>
        </MemoryRouter>,
      );
      await expect.element(screen.getByText("Nguyễn Minh Anh")).toBeVisible();
      const row = screen.container.querySelector<HTMLElement>(
        ".user-directory-row",
      )!;
      const rowBox = row.getBoundingClientRect();
      const role = row
        .querySelector<HTMLElement>(".user-directory-cell-role")!
        .getBoundingClientRect();
      const status = row
        .querySelector<HTMLElement>(".user-directory-cell-status")!
        .getBoundingClientRect();
      const date = row
        .querySelector<HTMLElement>(".user-directory-created")!
        .getBoundingClientRect();
      expect(status.left).toBeGreaterThanOrEqual(role.right);
      expect(date.top).toBeGreaterThanOrEqual(status.bottom);
      expect(date.left).toBeGreaterThanOrEqual(rowBox.left);
      expect(date.right).toBeLessThanOrEqual(rowBox.right);
      expect(date.bottom).toBeLessThanOrEqual(rowBox.bottom);
      expect(rowBox.right).toBeLessThanOrEqual(width);
      expect(row.scrollWidth).toBeLessThanOrEqual(Math.ceil(rowBox.width));
      const identity = row.querySelector<HTMLElement>(
        ".user-directory-identity",
      )!;
      const title = identity.querySelector<HTMLElement>("h3")!;
      const email = identity.querySelector<HTMLElement>("p span")!;
      for (const text of [title, email]) {
        expect(getComputedStyle(text).whiteSpace).toBe("normal");
        expect(getComputedStyle(text).overflow).toBe("visible");
        expect(text.getBoundingClientRect().right).toBeLessThanOrEqual(
          identity.getBoundingClientRect().right + 1,
        );
      }
      expect(email.getBoundingClientRect().height).toBeGreaterThan(
        parseFloat(getComputedStyle(email).lineHeight),
      );
    },
  );
  it("reports the total directory count beyond the visible page", async () => {
    listState.total = 57;
    const screen = await render(mountList());
    await expect
      .element(screen.getByText("57 tài khoản", { exact: true }))
      .toBeVisible();
    expect(screen.container.querySelectorAll("tbody tr")).toHaveLength(1);
  });

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
    // The role and status chips are no-props `useRecordContext()` components:
    // they render each row's own record or nothing at all. `exact` keeps the
    // role chip distinct from the page heading's "Quản trị truy cập" eyebrow.
    await expect
      .element(screen.getByText("Tuyển dụng", { exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Quản trị", { exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Hoạt động", { exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Vô hiệu", { exact: true }))
      .toBeVisible();
    // The avatar cell is Untitled UI's `Avatar`, fed the record's initials: the
    // first and last words of a Vietnamese name.
    const avatars = Array.from(
      screen.container.querySelectorAll(".user-directory-cell-avatar"),
    );
    expect(avatars.map((cell) => cell.textContent?.trim())).toEqual([
      "NA",
      "TB",
    ]);
    expect(avatars[0]?.querySelector("img")).toBeNull();
  });

  it("names each account's row actions and keeps create reachable", async () => {
    const screen = await render(mountList());
    // The row exposes every action as its own labelled control: the edit link
    // and the three buttons, each named for the account it acts on.
    for (const name of [
      "Sửa Nguyễn Minh Anh",
      "Vô hiệu hóa Nguyễn Minh Anh",
      "Đổi mật khẩu Nguyễn Minh Anh",
      "Xóa vĩnh viễn Nguyễn Minh Anh",
    ]) {
      await expect
        .element(
          screen.getByRole(name.startsWith("Sửa") ? "link" : "button", {
            name,
            exact: true,
          }),
        )
        .toBeVisible();
    }

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
