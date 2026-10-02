import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  DataProviderContext,
  NotificationContext,
  ResourceContextProvider,
  StoreContextProvider,
  TestMemoryRouter,
  memoryStore,
} from "ra-core";
import { Route, Routes } from "react-router";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import "./users.css";
import { TestMessages } from "../providers/commons/TestMessages";
import { UserCreate } from "./UserCreate";
import { UserEdit } from "./UserEdit";

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
const account = {
  id: 7,
  email: "recruiter@vfic.dev",
  full_name: "Nguyễn Minh Anh",
  role: "recruiter",
  disabled: false,
};

const mountAccountForm = (
  children: ReactNode,
  initialEntries: string[] = ["/"],
) => (
  <TestMemoryRouter initialEntries={initialEntries}>
    <QueryClientProvider client={new QueryClient()}>
      <TestMessages>
        <StoreContextProvider value={memoryStore()}>
          <DataProviderContext.Provider
            value={
              {
                create,
                getList: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
                getOne: vi.fn(() => Promise.resolve({ data: account })),
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
              <ResourceContextProvider value="users">
                <div className="workspace-frame-content">{children}</div>
              </ResourceContextProvider>
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
    expect(submit.element().getBoundingClientRect().height).toBe(36);
    // Both footer controls are Untitled UI `Button`s: without `.uu-scope` the
    // secondary one resolves `bg-primary` to the console's slate action fill
    // and paints the library's dark secondary ink on it (1.96:1).
    expect(submit.element().closest(".uu-scope")).not.toBeNull();
    const cancel = screen.getByRole("link", { name: "Hủy" });
    expect(cancel).toBeDefined();
    expect(cancel.element().closest(".uu-scope")).not.toBeNull();

    await page.viewport(phone, 844);
    await expect.element(submit).toBeVisible();
    await page.viewport(desktop, 720);
  });

  it.each([320, phone, desktop])(
    "uses compact mouse-operated controls and preserves44px password actions at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await renderedForm();
      const email = screen.getByRole("textbox", { name: "Email" });
      await expect.element(email).toBeVisible();

      const inputs = screen.container.querySelectorAll<HTMLInputElement>(
        ".user-account-field input",
      );
      expect(inputs).toHaveLength(4);
      for (const input of inputs) {
        const controlHeight = width < 768 ? 40 : 36;
        expect(input.getBoundingClientRect().height).toBeLessThanOrEqual(
          controlHeight,
        );
        expect(input.parentElement!.getBoundingClientRect().height).toBe(
          controlHeight,
        );
        expect(getComputedStyle(input).fontSize).toBe("12px");
      }
      const role = screen.getByRole("button", { name: /Vai trò/ }).element();
      expect(role.getBoundingClientRect().height).toBe(width < 768 ? 40 : 36);
      const value = role.querySelector("p")!;
      expect(getComputedStyle(value).fontSize).toBe("12px");
      expect(getComputedStyle(role).borderTopWidth).toBe("1px");
      const icon = screen.container.querySelector<HTMLElement>(
        ".user-account-form-icon",
      )!;
      expect(icon.getBoundingClientRect().width).toBe(20);
      expect(getComputedStyle(icon).borderTopWidth).toBe("0px");
      expect(getComputedStyle(icon).backgroundColor).toBe("rgba(0, 0, 0, 0)");
      for (const action of screen.container.querySelectorAll(
        ".user-account-form-actions > *",
      )) {
        expect(action.getBoundingClientRect().height).toBe(
          width < 768 ? 40 : 36,
        );
      }
      if (width < 768) {
        for (const action of screen.container.querySelectorAll(
          ".user-account-field button[aria-pressed]",
        )) {
          expect(action.getBoundingClientRect().height).toBeGreaterThanOrEqual(
            44,
          );
        }
      }
    },
  );

  it.each([desktop, phone])(
    "keeps the account switch visible in both states at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      const screen = await render(
        mountAccountForm(
          <Routes>
            <Route path="/users/:id" element={<UserEdit />} />
          </Routes>,
          ["/users/7"],
        ),
      );
      const toggle = screen.getByRole("switch", {
        name: "Vô hiệu hóa tài khoản",
      });
      await expect.element(toggle).toBeVisible();
      const shell = toggle.element().closest(".uu-scope")!;
      const track = shell.querySelector<HTMLElement>(
        ":scope > div.rounded-full",
      )!;
      const thumb = track.firstElementChild!;
      expect(getComputedStyle(track).borderTopWidth).toBe("1px");
      expect(getComputedStyle(thumb).borderTopWidth).toBe("1px");
      const inactiveColor = getComputedStyle(track).backgroundColor;
      expect(getComputedStyle(thumb).backgroundColor).not.toBe(inactiveColor);
      if (width === phone) {
        expect(shell.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
        expect(shell.getBoundingClientRect().width).toBeGreaterThanOrEqual(44);
      }
      await screen.getByText("Vô hiệu hóa tài khoản", { exact: true }).click();
      await expect.element(toggle).toBeChecked();
      expect(getComputedStyle(track).backgroundColor).not.toBe(inactiveColor);
      expect(getComputedStyle(thumb).backgroundColor).not.toBe(
        getComputedStyle(track).backgroundColor,
      );
    },
  );
});

describe("account form validation", () => {
  it("explains a short password at its field before sending it to the server", async () => {
    create.mockClear();
    const screen = await renderedForm();
    await screen
      .getByRole("textbox", { name: "Email" })
      .fill("recruiter@vfic.dev");
    await screen
      .getByRole("textbox", { name: "Họ và tên" })
      .fill("Nguyễn Minh Anh");
    await screen.getByLabelText(/^Mật khẩu/).fill("1234567");
    await screen.getByLabelText(/Xác nhận mật khẩu/).fill("1234567");
    await screen.getByRole("button", { name: "Tạo tài khoản" }).click();
    await expect
      .element(screen.getByText("Mật khẩu phải có ít nhất 8 ký tự."))
      .toBeVisible();
    expect(create).not.toHaveBeenCalled();
  });

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
    await screen.getByLabelText(/^Mật khẩu/).fill("matkhau8");
    await screen.getByLabelText(/Xác nhận mật khẩu/).fill("matkhau8");

    // The browser's own constraint stops a value with no `@` before the form
    // ever sees it; `a@b` clears that and is still not an address react-admin
    // accepts, so the Vietnamese message is what the recruiter sees.
    await screen.getByRole("textbox", { name: "Email" }).fill("a@b");
    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();

    await expect
      .poll(
        () =>
          screen.container.textContent?.includes(
            "Email chưa đúng định dạng.",
          ) ?? false,
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
    await screen.getByLabelText(/^Mật khẩu/).fill("matkhau8");
    await screen.getByLabelText(/Xác nhận mật khẩu/).fill("matkhau8");

    await screen.getByRole("button", { name: /Tạo tài khoản/ }).click();

    const pending = screen.getByRole("button", { name: "Đang tạo" });
    await expect.element(pending).toBeVisible();
    await expect
      .element(screen.getByRole("textbox", { name: "Email" }))
      .toBeDisabled();
    await expect
      .element(screen.getByRole("link", { name: "Hủy" }))
      .toHaveAttribute("aria-disabled", "true");

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
