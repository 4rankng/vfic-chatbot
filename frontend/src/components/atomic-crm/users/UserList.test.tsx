import { type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UserAccount } from "../types";
import "@/index.css";

const user: UserAccount = {
  id: "user-1",
  email: "recruiter@vfic.dev",
  full_name: "Nguyễn Minh Anh",
  role: "recruiter",
  disabled: false,
  created_at: "2026-07-22T10:00:00Z",
  updated_at: "2026-07-22T10:00:00Z",
};

vi.mock("ra-core", () => ({
  ListBase: ({ children }: { children: ReactNode }) => children,
  RecordContextProvider: ({ children }: { children: ReactNode }) => children,
  useCreatePath: () => () => "/users/create",
  useListContext: () => ({ data: [user], isPending: false }),
  usePermissions: () => ({ permissions: "admin", isPending: false }),
  useTranslate: () => (_key: string, options?: { smart_count?: number }) =>
    options?.smart_count ? "Tài khoản" : "",
}));

vi.mock("./UserActions", () => ({
  UserActions: () => <button type="button">Mở thao tác</button>,
}));

vi.mock("./UserBadges", () => ({
  UserRoleBadge: () => <span>Tuyển dụng</span>,
  UserStatusBadge: () => <span>Hoạt động</span>,
}));

import { UserList } from "./UserList";

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 720);
});

describe("UserList", () => {
  it("keeps the primary mobile action named and flattens the account list", async () => {
    await page.viewport(390, 844);
    const screen = await render(
      <MemoryRouter>
        <UserList />
      </MemoryRouter>,
    );

    const create = screen.getByRole("link", { name: "Tạo tài khoản" });
    await expect.element(create).toBeVisible();
    expect(
      getComputedStyle(create.element().querySelector("span")!).display,
    ).not.toBe("none");

    const directory = screen.container.querySelector<HTMLElement>(
      ".user-directory-card",
    )!;
    const row = screen.container.querySelector<HTMLElement>(
      ".user-directory-row",
    )!;

    expect(getComputedStyle(directory).borderRadius).toBe("0px");
    expect(getComputedStyle(row).backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(row.querySelector("[data-slot='card']")).toBeNull();
    await expect.element(screen.getByText("Nguyễn Minh Anh")).toBeVisible();
    await expect.element(screen.getByText("Hoạt động")).toBeVisible();
  });

  it("keeps mobile account rows compact with the metadata still visible", async () => {
    // Rendered counterpart of the former users.css source-text pins: the
    // computed styles prove the 760px rules actually apply to a rendered row,
    // and the metadata children staying displayed proves nothing is hidden.
    await page.viewport(390, 844);
    const screen = await render(
      <MemoryRouter>
        <UserList />
      </MemoryRouter>,
    );

    const row = screen.container.querySelector<HTMLElement>(
      ".user-directory-row",
    )!;
    const rowStyles = getComputedStyle(row);
    expect(rowStyles.minHeight).toBe("84px");
    expect(rowStyles.rowGap).toBe("4px");
    expect(rowStyles.paddingTop).toBe("8px");
    expect(rowStyles.paddingBottom).toBe("8px");

    const meta = row.querySelector<HTMLElement>(".user-directory-meta")!;
    const metaStyles = getComputedStyle(meta);
    expect(metaStyles.display).toBe("grid");
    expect(meta.children.length).toBeGreaterThanOrEqual(3);
    for (const child of Array.from(meta.children)) {
      expect(getComputedStyle(child).display).not.toBe("none");
    }

    await page.viewport(1280, 720);
  });
});
