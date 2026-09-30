import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  DataProviderContext,
  ListBase,
  NotificationContextProvider,
  TestMemoryRouter,
  useRecordContext,
} from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import tableSource from "../../application/table/table.tsx?raw";
import { TestMessages } from "../providers/commons/TestMessages";
import { ListTable } from "./list-table";

// TEST-17 shape: the real `ListBase` and the real list context, with a data
// provider stub the test controls. The assertions are what a recruiter sees and
// what react-admin is asked for — never a class name.
type Account = {
  id: string;
  full_name: string;
  role: string;
};

const accounts: Account[] = [
  { id: "user-1", full_name: "Nguyễn Minh Anh", role: "Tuyển dụng" },
  { id: "user-2", full_name: "Trần Quốc Bảo", role: "Quản trị" },
  { id: "user-3", full_name: "Lê Thu Hà", role: "Tuyển dụng" },
];

const getList = vi.fn();
const dataProvider = {
  getList,
  getOne: vi.fn(() => Promise.resolve({ data: accounts[0] })),
  getMany: vi.fn(() => Promise.resolve({ data: [] })),
  getManyReference: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
  create: vi.fn(() => Promise.resolve({ data: accounts[0] })),
  update: vi.fn(() => Promise.resolve({ data: accounts[0] })),
  updateMany: vi.fn(() => Promise.resolve({ data: [] })),
  delete: vi.fn(() => Promise.resolve({ data: accounts[0] })),
  deleteMany: vi.fn(() => Promise.resolve({ data: [] })),
};

const columns = [
  {
    id: "name",
    header: "Người dùng",
    isRowHeader: true,
    cell: (record: Account) => <span>{record.full_name}</span>,
  },
  {
    id: "role",
    header: "Vai trò",
    cell: (record: Account) => <span>{record.role}</span>,
  },
];

/**
 * A no-props cell component, exactly like the users directory's badges and row
 * actions: it can only render if the row provides react-admin's record context.
 */
const RoleFromRecord = () => {
  const record = useRecordContext<Account>();
  if (!record) return null;
  return <span>{record.role}</span>;
};

const recordDrivenColumns = [
  {
    id: "name",
    header: "Người dùng",
    isRowHeader: true,
    cell: (record: Account) => <span>{record.full_name}</span>,
  },
  {
    id: "role",
    header: "Vai trò",
    cell: () => <RoleFromRecord />,
  },
];

type MountOptions = {
  rowActions?: boolean;
  columns?: typeof columns;
};

const mount = ({
  rowActions,
  columns: columnsProp = columns,
}: MountOptions = {}) =>
  render(
    <TestMemoryRouter>
      <TestMessages>
        <QueryClientProvider client={new QueryClient()}>
          <DataProviderContext.Provider value={dataProvider as never}>
            <NotificationContextProvider>
              <ListBase resource="users" perPage={2}>
                <ListTable
                  ariaLabel="Danh sách tài khoản"
                  columns={columnsProp}
                  rowActions={
                    rowActions
                      ? (record) => (
                          <button type="button">{`Thao tác ${record.id}`}</button>
                        )
                      : undefined
                  }
                  header={
                    <header>
                      <p>{`${accounts.length} tài khoản`}</p>
                    </header>
                  }
                  empty={{
                    icon: <span aria-hidden="true" />,
                    title: "Chưa có tài khoản nào",
                    description: "Tạo tài khoản để phân quyền.",
                  }}
                />
              </ListBase>
            </NotificationContextProvider>
          </DataProviderContext.Provider>
        </QueryClientProvider>
      </TestMessages>
    </TestMemoryRouter>,
  );

beforeEach(() => {
  getList.mockReset();
  // A paginating provider, like the REST one: the third record only appears on
  // page two.
  getList.mockImplementation(
    (
      _resource: string,
      params: { pagination?: { page: number; perPage: number } },
    ) => {
      const { page = 1, perPage = 2 } = params.pagination ?? {};
      const start = (page - 1) * perPage;
      return Promise.resolve({
        data: accounts.slice(start, start + perPage),
        total: accounts.length,
      });
    },
  );
});

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

const headerTexts = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('[role="columnheader"]')).map(
    (node) => node.textContent,
  );

describe("kit list table", () => {
  it("hands each row's record to cells that read the record context", async () => {
    const screen = await mount({ columns: recordDrivenColumns });
    await expect
      .element(screen.getByRole("grid", { name: "Danh sách tài khoản" }))
      .toBeVisible();

    // Both cells are no-props components reading `useRecordContext()` — the
    // same shape as the users directory's badges and row actions. Each row
    // must provide its own record, the way react-admin's `Datagrid` does; a
    // missing context renders these cells as nothing at all.
    await expect.element(screen.getByText("Tuyển dụng")).toBeVisible();
    await expect.element(screen.getByText("Quản trị")).toBeVisible();
    expect(screen.container.querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("never generates a box from the row's own ::after", () => {
    // The vitest lane does not load the Tailwind layer, so the mechanism this
    // pins cannot be observed in rendered output here — it was reproduced and
    // fixed against real Chromium: any row-level `after:` utility forces
    // `content` onto the row's pseudo-element, and a generated box inside a
    // `<tr>` is wrapped in an anonymous table cell. That phantom auto column
    // takes an equal share of the fixed layout's leftover width and leaves the
    // header band short of the table edge. Cell-scoped (`[&>td]:after:*`)
    // utilities are unaffected — they live inside a cell, not the row.
    const rowSource = tableSource.slice(
      tableSource.indexOf("const TableRow"),
      tableSource.indexOf("TableRow.displayName"),
    );
    expect(rowSource).toContain("after:hidden");
    expect(rowSource).not.toMatch(/(?<![\]>:a-z])after:(?!hidden\b)[a-z]/);
  });

  it("renders one labelled table bound to the list records", async () => {
    const screen = await mount();
    // React Aria renders a focusable data table as a `grid`, so that is the
    // role the surface carries.
    const grid = screen.getByRole("grid", { name: "Danh sách tài khoản" });

    await expect.element(grid).toBeVisible();
    expect(headerTexts(screen.container)).toEqual(["Người dùng", "Vai trò"]);

    const rowHeaders = Array.from(
      screen.container.querySelectorAll('[role="rowheader"]'),
    );
    expect(rowHeaders.map((node) => node.textContent)).toEqual([
      "Nguyễn Minh Anh",
      "Trần Quốc Bảo",
    ]);
    await expect.element(screen.getByText("Quản trị")).toBeVisible();
    expect(screen.container.textContent).toContain("3 tài khoản");
    // Two records on the first page, so the third is not rendered yet.
    expect(screen.container.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(screen.container.textContent).not.toContain("Lê Thu Hà");
  });

  it("renders the caller's row actions in a trailing column", async () => {
    const screen = await mount({ rowActions: true });
    await expect
      .element(screen.getByRole("grid", { name: "Danh sách tài khoản" }))
      .toBeVisible();

    expect(headerTexts(screen.container)).toEqual([
      "Người dùng",
      "Vai trò",
      "Thao tác",
    ]);
    await expect
      .element(screen.getByRole("button", { name: "Thao tác user-1" }))
      .toBeVisible();
  });

  it("pages the list through react-admin's list context", async () => {
    const screen = await mount();

    await screen.getByRole("button", { name: "Trang tiếp" }).click();

    await expect
      .poll(() => getList.mock.calls.length)
      .toBeGreaterThanOrEqual(2);
    expect(getList.mock.lastCall?.[1]).toMatchObject({
      pagination: { page: 2, perPage: 2 },
    });
    const current = screen.getByRole("button", { name: "Trang 2" });
    await expect.element(current).toBeVisible();
    expect(current.element().getAttribute("aria-current")).toBe("page");
    // Page two carries the record the first page left out.
    await expect.element(screen.getByText("Lê Thu Hà")).toBeVisible();
    expect(screen.container.textContent).not.toContain("Trần Quốc Bảo");
  });

  it("keeps the empty state's Vietnamese copy when the list has no records", async () => {
    getList.mockImplementation(() => Promise.resolve({ data: [], total: 0 }));
    const screen = await mount();

    await expect
      .element(screen.getByText("Chưa có tài khoản nào"))
      .toBeVisible();
    await expect
      .element(screen.getByText("Tạo tài khoản để phân quyền."))
      .toBeVisible();
    expect(screen.container.querySelector("table")).toBeNull();
  });

  it("announces the loading state while the list is in flight", async () => {
    // A promise that never settles keeps the list pending for the assertion.
    // `Promise.withResolvers` is ES2024 and this project targets ES2022, so the
    // pending promise is built with an explicit resolver.
    getList.mockImplementation(() => new Promise(() => {}));
    const screen = await mount();

    // Geometry is not asserted: this lane does not load the Tailwind layer, so
    // a utility-sized skeleton has no box here even though it does in the app.
    // The accessible name and the row placeholders are what the surface owns.
    const status = screen.getByRole("status", { name: "Đang tải danh sách" });
    expect(status.element()).toBeInstanceOf(HTMLElement);
    expect(status.element().children).toHaveLength(4);
    expect(screen.container.querySelector("table")).toBeNull();
  });
});
