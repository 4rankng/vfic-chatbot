import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TestMemoryRouter } from "ra-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import type * as ApiClientModule from "@/lib/apiClient";
import type * as RaCoreModule from "ra-core";

import { TestMessages } from "../providers/commons/TestMessages";

/**
 * ProfilePage renders the signed-in user's own record and saves it through
 * `PATCH /api/v1/users/me`. Only the data boundary is stubbed (`apiJson` and
 * the four data/locale hooks); the form engine is the real one — react-admin's
 * `Form` is a react-hook-form `FormProvider`, and the Untitled UI fields join it
 * through `useInput`.
 *
 * Every assertion is behavioural: the read/edit states, the accessible name of
 * each control, and the exact payload the update sends. Nothing pins the
 * primitives' markup or class names.
 */

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn(),
  notify: vi.fn(),
  refetchIdentity: vi.fn(),
  refetchUser: vi.fn(),
  logout: vi.fn(),
  profilePending: false,
  profileError: false,
}));

vi.mock("@/lib/apiClient", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClientModule>()),
  apiJson: mocks.apiJson,
}));

vi.mock("ra-core", async (importOriginal) => {
  const actual = await importOriginal<typeof RaCoreModule>();
  return {
    ...actual,
    useGetIdentity: () => ({
      identity: { id: 1, fullName: "Nguyễn Văn A" },
      refetch: mocks.refetchIdentity,
    }),
    useGetOne: () => ({
      data:
        mocks.profilePending || mocks.profileError
          ? undefined
          : {
              id: 1,
              full_name: "Nguyễn Văn A",
              email: "a@vfic.com.vn",
            },
      refetch: mocks.refetchUser,
      isPending: mocks.profilePending,
      isError: mocks.profileError,
    }),
    useNotify: () => mocks.notify,
    useLogout: () => mocks.logout,
  };
});

import { ProfilePage } from "./ProfilePage";

const renderProfile = async () =>
  render(
    <TestMemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: {} },
          })
        }
      >
        <TestMessages>
          <ProfilePage />
        </TestMessages>
      </QueryClientProvider>
    </TestMemoryRouter>,
  );

beforeEach(() => {
  mocks.apiJson.mockReset();
  mocks.apiJson.mockResolvedValue({});
  mocks.notify.mockReset();
  mocks.refetchIdentity.mockReset();
  mocks.refetchUser.mockReset();
  mocks.logout.mockReset();
  mocks.profilePending = false;
  mocks.profileError = false;
});

afterEach(async () => {
  await cleanup();
});

describe("ProfilePage", () => {
  it("announces a pending profile without presenting blank editable data", async () => {
    mocks.profilePending = true;
    const screen = await renderProfile();
    await expect.element(screen.getByRole("status")).toBeVisible();
    expect(screen.container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.container.textContent).not.toContain("Chưa cập nhật");
  });

  it("offers a retry when the profile cannot be loaded", async () => {
    mocks.profileError = true;
    const screen = await renderProfile();
    await expect
      .element(screen.getByText("Chưa tải được hồ sơ cá nhân."))
      .toBeVisible();
    await screen.getByRole("button", { name: "Thử lại" }).click();
    expect(mocks.refetchUser).toHaveBeenCalledTimes(1);
    expect(mocks.apiJson).not.toHaveBeenCalled();
  });

  it("keeps the submitted edit locked until the profile write finishes", async () => {
    let finish!: (value: object) => void;
    mocks.apiJson.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const screen = await renderProfile();
    await screen.getByRole("button", { name: "Sửa" }).click();
    await screen.getByRole("textbox", { name: /Họ tên/ }).fill("Tên đang lưu");
    await screen.getByRole("button", { name: "Lưu" }).click();
    await expect.poll(() => mocks.apiJson.mock.calls.length).toBe(1);
    await expect
      .element(screen.getByRole("button", { name: "Hủy" }))
      .toBeDisabled();
    await expect
      .element(screen.getByRole("textbox", { name: /Họ tên/ }))
      .toBeDisabled();
    finish({});
    await expect
      .element(screen.getByRole("button", { name: "Sửa" }))
      .toBeVisible();
  });

  it("shows the signed-in account read-only until editing starts", async () => {
    const screen = await renderProfile();

    await expect
      .element(screen.getByRole("heading", { name: "Hồ sơ cá nhân" }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Nguyễn Văn A · a@vfic.com.vn"))
      .toBeVisible();
    await expect.element(screen.getByText("Họ tên")).toBeVisible();
    await expect
      .element(screen.getByText("a@vfic.com.vn", { exact: true }))
      .toBeVisible();

    // Read mode has no editable control for the record fields.
    expect(screen.container.querySelectorAll("input")).toHaveLength(0);

    await expect
      .element(screen.getByRole("button", { name: "Sửa" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Đăng xuất" }))
      .toBeVisible();
  });

  it("edits the name and saves only the two profile fields", async () => {
    const screen = await renderProfile();

    await screen.getByRole("button", { name: "Sửa" }).click();

    const nameInput = screen.getByRole("textbox", { name: /Họ tên/ });
    const emailInput = screen.getByRole("textbox", { name: /Email/ });
    await expect.element(nameInput).toHaveValue("Nguyễn Văn A");
    await expect.element(emailInput).toHaveValue("a@vfic.com.vn");

    // The save action is inert until the form is dirty.
    const save = screen.getByRole("button", { name: "Lưu" });
    expect(save.element().hasAttribute("disabled")).toBe(true);

    await nameInput.fill("Trần Thị B");
    await save.click();

    await expect.poll(() => mocks.apiJson.mock.calls.length).toBe(1);
    expect(mocks.apiJson).toHaveBeenCalledWith("/api/v1/users/me", {
      method: "PATCH",
      body: { full_name: "Trần Thị B", email: "a@vfic.com.vn" },
    });
  });

  it("abandons the edit without sending a request", async () => {
    const screen = await renderProfile();

    await screen.getByRole("button", { name: "Sửa" }).click();
    await screen.getByRole("textbox", { name: /Họ tên/ }).fill("Tên đã sửa");
    await screen.getByRole("button", { name: "Hủy" }).click();

    expect(mocks.apiJson).not.toHaveBeenCalled();
    await expect.element(screen.getByText("Họ tên")).toBeVisible();
    expect(screen.container.querySelectorAll("input")).toHaveLength(0);
  });

  it("ends the session from the session section", async () => {
    const screen = await renderProfile();

    await screen.getByRole("button", { name: "Đăng xuất" }).click();
    expect(mocks.logout).toHaveBeenCalledTimes(1);
  });
});
