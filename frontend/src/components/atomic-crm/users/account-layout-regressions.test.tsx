import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  DataProviderContext,
  NotificationContext,
  StoreContextProvider,
  TestMemoryRouter,
  memoryStore,
} from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import "./users.css";
import { TestMessages } from "../providers/commons/TestMessages";
import { UserCreate } from "./UserCreate";

// TEST-17 — this replaces the account-layout suite that pinned the removed
// shadcn controls (`[data-slot="form-control"]`, `[data-slot="select-trigger"]`,
// `[data-slot="button"]`) and the grid geometry measured around them. The
// account form now renders the kit's react-admin bound Untitled UI controls, so
// what it owes a recruiter is behaviour: Vietnamese validation that fires, a
// payload that carries the typed values, and a submit that reports progress.
//
// Everything below mounts the real `UserCreate` — ra-core's `CreateBase`,
// `Form` and the shipped Vietnamese catalog included.

const desktop = 1280;
const phone = 390;

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 720);
});

const create = vi.fn(() => Promise.resolve({ data: { id: 7 } }));
const notify = vi.fn();

const mountAccountForm = (children: ReactNode) => (
  <TestMemoryRouter>
    <QueryClientProvider client={new QueryClient()}>
      <TestMessages>
        <StoreContextProvider value={memoryStore()}>
          <DataProviderContext.Provider
            value={
              {
                create,
                getList: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
                getOne: vi.fn(() => Promise.resolve({ data: {} })),
                getMany: vi.fn(() => Promise.resolve({ data: [] })),
                getManyReference: vi.fn(() =>
                  Promise.resolve({ data: [], total: 0 }),
                ),
                update: vi.fn(() => Promise.resolve({ data: {} })),
                delete: vi.fn(() => Promise.resolve({ data: {} })),
                updateMany: vi.fn(() => Promise.resolve({ data: [] })),
                deleteMany: vi.fn(() => Promise.resolve({ data: [] })),
              } as never
            }
          >
            <NotificationContext.Provider value={[notify, vi.fn()] as never}>
              {children}
            </NotificationContext.Provider>
          </DataProviderContext.Provider>
        </StoreContextProvider>
      </TestMessages>
    </QueryClientProvider>
  </TestMemoryRouter>
);

const renderedForm = () => render(mountAccountForm(<UserCreate />));

describe("account form controls", () => {
  it("exposes every field by name as a labelled control", async () => {
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    await expect
      .element(screen.getByRole("textbox", { name: "Email" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("textbox", { name: "Họ và tên" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: /Vai trò/ }))
      .toBeVisible();
    await expect
      .element(
        // A password field has no `textbox` role, so it is reached by its label;
        // the regex tolerates the required marker the label appends.
        screen.getByLabelText(/^Mật khẩu/),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("textbox", { name: "Xác nhận mật khẩu" }))
      .toBeVisible();

    // React Aria's default `native` validation would set the `required`
    // attribute and the browser would block the submit before react-admin's
    // Vietnamese validation ran.
    const email = screen.getByRole("textbox", { name: "Email" });
    expect(email.element().getAttribute("aria-required")).toBe("true");
    expect(email.element().hasAttribute("required")).toBe(false);
    expect(email.element().closest(".uu-scope")).not.toBeNull();
  });

  it("keeps the actions on their own band at the comfortable height", async () => {
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    const submit = screen.getByRole("button", { name: /Tạo tài khoản/ });
    await expect.element(submit).toBeVisible();
    // 44px is the console's touch target; the kit buttons carry `min-h-11`
    // themselves now that the sheet no longer sizes them.
    expect(submit.element().className).toContain("min-h-11");
    expect(screen.getByRole("link", { name: "Hủy" })).toBeDefined();

    await page.viewport(phone, 844);
    await expect.element(submit).toBeVisible();
    await page.viewport(desktop, 720);
  });
});

describe("account form validation", () => {
  it("blocks the create call and names every empty required field", async () => {
    create.mockClear();
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();

    await expect
      .poll(
        () =>
          (screen.container.textContent ?? "").split("Vui lòng nhập thông tin.")
            .length - 1,
      )
      .toBeGreaterThanOrEqual(4);
    expect(create).not.toHaveBeenCalled();
  });

  it("rejects a malformed email before sending data", async () => {
    create.mockClear();
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    await screen
      .getByRole("textbox", { name: "Họ và tên" })
      .fill("Nguyễn Minh Anh");
    await screen.getByRole("button", { name: /Vai trò/ }).click();
    await screen.getByRole("option", { name: "Tuyển dụng" }).click();
    await screen
      .getByLabelText(/^Mật khẩu/)
      .fill("matkhau8");
    await screen
      .getByLabelText(/Xác nhận mật khẩu/)
      .fill("matkhau8");

    // The browser's own constraint stops a value with no `@` before the form
    // ever sees it; `a@b` clears that and is still not an address react-admin
    // accepts, so the Vietnamese message is what the recruiter sees.
    await screen.getByRole("textbox", { name: "Email" }).fill("a@b");
    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();

    await expect
      .poll(
        () =>
          screen.container.textContent?.includes("Email chưa đúng định dạng.") ??
          false,
      )
      .toBe(true);
    expect(create).not.toHaveBeenCalled();
  });

  it("submits the typed values and reports progress once they are valid", async () => {
    let resolveCreate!: (value: { data: { id: number } }) => void;
    const promise = new Promise<{ data: { id: number } }>((resolve) => {
      resolveCreate = resolve;
    });
    create.mockClear();
    create.mockReturnValueOnce(promise as never);
    await page.viewport(desktop, 720);
    const screen = await renderedForm();

    await screen
      .getByRole("textbox", { name: "Email" })
      .fill("recruiter@vfic.dev");
    await screen
      .getByRole("textbox", { name: "Họ và tên" })
      .fill("Nguyễn Minh Anh");
    await screen
      .getByLabelText(/^Mật khẩu/)
      .fill("matkhau8");
    await screen
      .getByLabelText(/Xác nhận mật khẩu/)
      .fill("matkhau8");

    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();

    const pending = screen.getByRole("button", { name: "Đang tạo" });
    await expect.element(pending).toBeVisible();

    resolveCreate({ data: { id: 7 } });
    await expect.poll(() => create.mock.calls.length).toBe(1);
    const [resource, params] = create.mock.calls[0] as unknown as [
      string,
      { data: Record<string, unknown> },
    ];
    expect(resource).toBe("users");
    expect(params.data).toMatchObject({
      email: "recruiter@vfic.dev",
      full_name: "Nguyễn Minh Anh",
      role: "recruiter",
    });
    // The confirm-password field is a client-side check only; it must not be
    // shipped to the users endpoint.
    expect(params.data).not.toHaveProperty("confirm_password");
  });
});
