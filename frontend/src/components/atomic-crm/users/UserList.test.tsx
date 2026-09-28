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
    listState: { data: accounts, isPending: false, total: accounts.length },
  };
});

vi.mock("ra-core", () => ({
  ListBase: ({ children }: { children: ReactNode }) => children,
  RecordContextProvider: ({ children }: { children: ReactNode }) => children,
  useCreatePath: () => () => "/users/create",
  useListContext: () => listState,
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

const mountList = () => (
  <MemoryRouter>
    <UserList />
  </MemoryRouter>
);

afterEach(async () => {
  listState.data = accounts;
  await cleanup();
  await page.viewport(1280, 720);
});

describe("UserList", () => {
  it("lists the directory as one table with real column headers and a count line", async () => {
    await page.viewport(1280, 844);
    listState.data = [...accounts, secondAccount];
    const screen = await render(mountList());

    const surface = screen.container.querySelector<HTMLElement>(
      ".user-directory-card",
    )!;
    const table = surface.querySelector<HTMLTableElement>("table")!;
    expect(table).toBeInstanceOf(HTMLTableElement);
    // The previous surface was an aria-hidden column strip over a grid list.
    expect(table.getAttribute("aria-label")).toBe("Danh sách tài khoản");

    const heads = Array.from(
      table.querySelectorAll<HTMLTableCellElement>("thead th"),
    );
    expect(heads.map((th) => th.textContent?.trim())).toEqual([
      "Ảnh đại diện",
      "Người dùng",
      "Vai trò",
      "Trạng thái",
      "Ngày tạo",
      "Thao tác",
    ]);
    expect(heads.map((th) => th.scope)).toEqual(
      Array(heads.length).fill("col"),
    );

    const rows = table.querySelectorAll<HTMLTableRowElement>(
      "tbody tr.user-directory-row",
    );
    expect(rows).toHaveLength(2);
    expect(surface.textContent).toContain("2 tài khoản");
    expect(getComputedStyle(rows[0]).display).toBe("table-row");
  });

  it("replaces the bespoke empty card with the kit empty state", async () => {
    listState.data = [];
    const screen = await render(mountList());

    expect(screen.container.querySelector(".user-directory-card")).toBeNull();
    const status =
      screen.container.querySelector<HTMLElement>('[role="status"]')!;
    expect(status.textContent).toContain("Chưa có tài khoản nào");
    expect(status.textContent).toContain(
      "Tạo tài khoản để phân quyền cho đội tuyển dụng.",
    );
  });

  it("keeps the primary mobile action named and flattens the account list", async () => {
    await page.viewport(390, 844);
    const screen = await render(mountList());

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
    // The phone row is linearised: the table box roles are dropped so the row
    // can lay its six cells out instead of forcing six table columns into 390px.
    expect(getComputedStyle(directory.querySelector("table")!).display).toBe(
      "block",
    );
    expect(getComputedStyle(directory.querySelector("thead")!).display).toBe(
      "none",
    );
    await expect.element(screen.getByText("Nguyễn Minh Anh")).toBeVisible();
    await expect.element(screen.getByText("Hoạt động")).toBeVisible();
  });

  it("keeps mobile account rows compact with every metadata field visible", async () => {
    // Rendered counterpart of the former users.css source-text pins: the
    // computed styles prove the 760px rules actually apply to a rendered row,
    // and the metadata cells sharing one line proves nothing is hidden or
    // pushed out of the card.
    await page.viewport(390, 844);
    const screen = await render(mountList());

    const row = screen.container.querySelector<HTMLElement>(
      ".user-directory-row",
    )!;
    const rowStyles = getComputedStyle(row);
    expect(rowStyles.minHeight).toBe("84px");
    expect(rowStyles.rowGap).toBe("4px");
    expect(rowStyles.paddingTop).toBe("8px");
    expect(rowStyles.paddingBottom).toBe("8px");

    const metadata = ["role", "status", "created"].map(
      (field) =>
        row.querySelector<HTMLElement>(`.user-directory-cell-${field}`)!,
    );
    for (const cell of metadata) {
      expect(cell).toBeInstanceOf(HTMLElement);
      expect(getComputedStyle(cell).display, cell.outerHTML).not.toBe("none");
    }

    // All three share the band's line, closed by the creation date in desktop
    // column order.
    const centres = metadata.map((cell) => {
      const rect = cell.getBoundingClientRect();
      return rect.top + rect.height / 2;
    });
    expect(Math.max(...centres) - Math.min(...centres)).toBeLessThanOrEqual(2);
    expect(metadata[2].getBoundingClientRect().left).toBeGreaterThan(
      metadata[0].getBoundingClientRect().left,
    );

    // ...and the band sits under the identity, which keeps the full width above
    // it rather than being narrowed by the badges.
    const identity = row.querySelector<HTMLElement>(
      ".user-directory-cell-identity",
    )!;
    const identityRect = identity.getBoundingClientRect();
    for (const cell of metadata) {
      expect(cell.getBoundingClientRect().top).toBeGreaterThanOrEqual(
        identityRect.bottom,
      );
    }
    expect(identityRect.width).toBeGreaterThan(
      metadata[0].getBoundingClientRect().width * 2,
    );

    await page.viewport(1280, 720);
  });
});
