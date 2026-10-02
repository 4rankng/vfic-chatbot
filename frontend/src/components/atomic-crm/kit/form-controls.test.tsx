import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DataProviderContext, Form, TestMemoryRouter, required } from "ra-core";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

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

const mountField = (field: ReactNode, onSubmit = vi.fn()) =>
  render(
    <TestMemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <DataProviderContext.Provider value={noopDataProvider as never}>
          <TestMessages>
            <Form resource="users" onSubmit={onSubmit}>
              {field}
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
  it.each([320, 390, 1440])(
    "matches text fields and custom selects to the compact scale at %ipx",
    async (width) => {
      await page.viewport(width, 900);
      const screen = await mount(vi.fn());
      const input = screen.getByRole("textbox", { name: "Email" }).element();
      const field = input.closest('[class~="group/input"]')!;
      const height = width < 768 ? 40 : 36;
      expect(field.getBoundingClientRect().height).toBe(height);
      expect(input.getBoundingClientRect().height).toBeLessThanOrEqual(height);
      expect(getComputedStyle(input).fontSize).toBe(
        window.matchMedia("(pointer: coarse)").matches ? "16px" : "12px",
      );
      const label = input
        .closest(".console-form-control")!
        .querySelector("label")!;
      expect(getComputedStyle(label).fontSize).toBe("13px");
      const select = screen.getByRole("button", { name: /Vai trò/ });
      expect(select.element().getBoundingClientRect().height).toBe(height);
      expect(
        getComputedStyle(select.element().querySelector("p")!).fontSize,
      ).toBe("12px");
      await select.click();
      const option = screen.getByRole("option", { name: "Quản trị" });
      await expect.element(option).toBeVisible();
      expect(
        getComputedStyle(option.element().querySelector('[slot="label"]')!)
          .fontSize,
      ).toBe("12px");
    },
  );

  it("reveals and masks a password through a Vietnamese action without submitting the form", async () => {
    const onSubmit = vi.fn();
    const screen = await mountField(
      <FormTextInput
        source="password"
        label="Mật khẩu"
        type="password"
        isRequired
        validate={required(EMPTY)}
      />,
      onSubmit,
    );
    const password = screen.getByLabelText(/Mật khẩu/);
    await screen.getByRole("button", { name: "Lưu" }).click();
    await expect.element(screen.getByText(EMPTY)).toBeVisible();
    expect(password.element().hasAttribute("required")).toBe(false);
    await expect.element(password).toHaveFocus();
    await password.fill("mat-khau-kiem-thu");
    expect(password.element().getAttribute("type")).toBe("password");

    await screen.getByRole("button", { name: "Hiện mật khẩu" }).click();

    expect(password.element().getAttribute("type")).toBe("text");
    expect(onSubmit).not.toHaveBeenCalled();
    await screen.getByRole("button", { name: "Ẩn mật khẩu" }).click();
    expect(password.element().getAttribute("type")).toBe("password");
    await screen.getByRole("button", { name: "Lưu" }).click();
    await expect.poll(() => onSubmit.mock.calls.length).toBe(1);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      password: "mat-khau-kiem-thu",
    });
  });

  it("focuses a required select's trigger when validation fails", async () => {
    const screen = await mountField(
      <FormSelect
        source="role"
        label="Vai trò"
        choices={choices}
        validate={required(EMPTY)}
      />,
    );

    await screen.getByRole("button", { name: "Lưu" }).click();

    await expect.element(screen.getByText(EMPTY)).toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: /Vai trò/ }))
      .toHaveFocus();
  });

  it("validates a checkbox and focuses its input without native validation", async () => {
    const onSubmit = vi.fn();
    const message = "Hãy xác nhận lựa chọn.";
    const screen = await mountField(
      <FormCheckbox
        source="confirmed"
        label="Xác nhận"
        isRequired
        validate={(value) => (value === true ? undefined : message)}
      />,
      onSubmit,
    );

    await screen.getByRole("button", { name: "Lưu" }).click();

    await expect.element(screen.getByText(message)).toBeVisible();
    const checkbox = screen.getByRole("checkbox", { name: "Xác nhận" });
    await expect.element(checkbox).toHaveFocus();
    expect(checkbox.element().hasAttribute("required")).toBe(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("validates a switch and connects its recovery text to the focused input", async () => {
    const onSubmit = vi.fn();
    const message = "Hãy bật thông báo trước khi lưu.";
    const screen = await mountField(
      <FormToggle
        source="notify"
        label="Nhận thông báo"
        validate={(value) => (value === true ? undefined : message)}
      />,
      onSubmit,
    );

    await screen.getByRole("button", { name: "Lưu" }).click();

    await expect.element(screen.getByRole("alert")).toHaveTextContent(message);
    const toggle = screen.getByRole("switch", { name: "Nhận thông báo" });
    await expect.element(toggle).toHaveFocus();
    expect(toggle.element().getAttribute("aria-describedby")).toBe(
      screen.getByRole("alert").element().id,
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

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
      .element(screen.getByRole("switch", { name: "Vô hiệu hóa tài khoản" }))
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
      .poll(() => (screen.container.textContent ?? "").split(EMPTY).length - 1)
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
