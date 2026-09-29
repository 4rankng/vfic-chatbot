import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DataProviderContext, Form, TestMemoryRouter, required } from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import { TestMessages } from "../providers/commons/TestMessages";
import {
  FormCheckbox,
  FormSelect,
  FormTextArea,
  FormTextInput,
  FormToggle,
} from "./form-controls";

// The form fields join react-admin's own form engine (`Form` is a
// react-hook-form `FormProvider`), so these tests mount the real `Form`, the
// real `useInput` and the shipped Vietnamese catalog, and assert what a
// recruiter's browser does: the accessible name, the required signal, and the
// values a submit carries.
const EMPTY = "Vui lòng nhập thông tin.";

const choices = [
  { id: "admin", name: "Quản trị" },
  { id: "recruiter", name: "Tuyển dụng" },
];

const noopDataProvider = {
  create: vi.fn(),
  getList: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
  getOne: vi.fn(() => Promise.resolve({ data: {} })),
  getMany: vi.fn(() => Promise.resolve({ data: [] })),
  getManyReference: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
  update: vi.fn(() => Promise.resolve({ data: {} })),
  updateMany: vi.fn(() => Promise.resolve({ data: [] })),
  delete: vi.fn(() => Promise.resolve({ data: {} })),
  deleteMany: vi.fn(() => Promise.resolve({ data: [] })),
};

const mount = (onSubmit: (values: Record<string, unknown>) => void) =>
  render(
    <TestMemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <DataProviderContext.Provider value={noopDataProvider as never}>
          <TestMessages>
            <Form resource="users" onSubmit={onSubmit}>
              <FormTextInput
                source="email"
                label="Email"
                type="email"
                isRequired
                validate={required(EMPTY)}
              />
              <FormTextInput
                source="full_name"
                label="Họ và tên"
                isRequired
                validate={required(EMPTY)}
              />
              <FormTextArea source="description" label="Mô tả" rows={3} />
              <FormSelect
                source="role"
                label="Vai trò"
                choices={choices}
                defaultValue="recruiter"
                isRequired
              />
              <FormToggle source="disabled" label="Vô hiệu hóa tài khoản" />
              <FormCheckbox source="notify" label="Nhận thông báo" />
              <button type="submit">Lưu</button>
            </Form>
          </TestMessages>
        </DataProviderContext.Provider>
      </QueryClientProvider>
    </TestMemoryRouter>,
  );

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

describe("kit form controls", () => {
  it("labels every control and keeps react-admin's validation in charge", async () => {
    const screen = await mount(vi.fn());

    const email = screen.getByRole("textbox", { name: "Email" });
    await expect.element(email).toBeVisible();
    // React Aria's default `native` validation would set the `required`
    // attribute, the browser would block the submit before react-admin
    // validates, and the Vietnamese message would never render.
    expect(email.element().getAttribute("aria-required")).toBe("true");
    expect(email.element().hasAttribute("required")).toBe(false);
    expect(email.element().closest(".uu-scope")).not.toBeNull();

    await expect
      .element(screen.getByRole("textbox", { name: "Họ và tên" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("textbox", { name: "Mô tả" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: /Vai trò/ }))
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("switch", { name: "Vô hiệu hóa tài khoản" }),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("checkbox", { name: "Nhận thông báo" }))
      .toBeVisible();
  });

  it("names every empty required field in Vietnamese and blocks the submit", async () => {
    const onSubmit = vi.fn();
    const screen = await mount(onSubmit);

    await screen.getByRole("button", { name: "Lưu" }).click();

    await expect
      .poll(
        () =>
          (screen.container.textContent ?? "").split(EMPTY).length - 1,
      )
      .toBeGreaterThanOrEqual(2);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits text, textarea, select, switch and checkbox values", async () => {
    const onSubmit = vi.fn();
    const screen = await mount(onSubmit);

    await screen.getByRole("textbox", { name: "Email" }).fill("a@vfic.dev");
    await screen
      .getByRole("textbox", { name: "Họ và tên" })
      .fill("Nguyễn Minh Anh");
    await screen.getByRole("textbox", { name: "Mô tả" }).fill("Ghi chú nội bộ");
    await screen.getByRole("button", { name: /Vai trò/ }).click();
    await screen.getByRole("option", { name: "Quản trị" }).click();
    // A user clicks the visible label, not the visually hidden input React
    // Aria renders for the switch and the checkbox.
    await screen.getByText("Vô hiệu hóa tài khoản").click();
    await screen.getByText("Nhận thông báo").click();
    await screen.getByRole("button", { name: "Lưu" }).click();

    await expect.poll(() => onSubmit.mock.calls.length).toBe(1);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      email: "a@vfic.dev",
      full_name: "Nguyễn Minh Anh",
      description: "Ghi chú nội bộ",
      role: "admin",
      disabled: true,
      notify: true,
    });
  });
});
