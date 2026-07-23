import type { FormEvent, ReactNode } from "react";
import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
}));

vi.mock("ra-core", () => ({
  CreateBase: ({ children }: { children: ReactNode }) => <>{children}</>,
  Form: ({
    children,
    onSubmit,
  }: {
    children: ReactNode;
    onSubmit: (data: Record<string, unknown>) => void;
  }) => (
    <form
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        onSubmit({});
      }}
    >
      {children}
    </form>
  ),
  useDataProvider: () => ({ create: vi.fn() }),
  useNotify: () => vi.fn(),
  useRedirect: () => mocks.redirect,
}));

vi.mock("@/components/admin/text-input", () => ({
  TextInput: ({ label }: { label: string }) => <input aria-label={label} />,
}));

vi.mock("./ProjectWorkspaceShell", () => ({
  ProjectWorkspaceShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));

import { ProjectCreate } from "./ProjectCreate";

describe("ProjectCreate", () => {
  beforeEach(() => {
    mocks.redirect.mockReset();
  });

  it("keeps the create form bounded and returns to the project list when closed", async () => {
    const screen = await render(<ProjectCreate />);

    expect(
      screen.container.querySelector(
        ".project-create-shell.mx-auto.w-full.max-w-4xl",
      ),
    ).not.toBeNull();

    await screen
      .getByRole("button", { name: "Đóng và quay lại danh sách dự án" })
      .click();

    expect(mocks.redirect).toHaveBeenCalledWith("/projects");
  });

  it("presents a clear knowledge choice and labels conditional fields", async () => {
    const screen = await render(<ProjectCreate />);
    const directMode = screen.getByRole("radio", {
      name: /Một nội dung/,
    });

    await expect.element(directMode).not.toBeChecked();
    await directMode.click();
    await expect.element(directMode).toBeChecked();
    expect(
      directMode.element().closest("[data-selected='true']"),
    ).not.toBeNull();

    await expect
      .element(
        screen.getByRole("heading", { name: "Giúp ứng viên tìm đúng dự án" }),
      )
      .toBeVisible();
    await expect.element(screen.getByLabelText("Tóm tắt *")).toBeVisible();
    await expect.element(screen.getByLabelText("Địa điểm *")).toBeVisible();
    await expect
      .element(screen.getByLabelText("Vị trí tuyển dụng"))
      .toBeVisible();
  });
});
