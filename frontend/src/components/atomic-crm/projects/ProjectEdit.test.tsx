import type { FormEvent, ReactNode } from "react";
import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../types";

const project: Project = {
  id: "project-1",
  name: "LG Display",
  slug: "lg-display",
  is_active: true,
  knowledge_mode: "RAG",
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
};

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  notify: vi.fn(),
  redirect: vi.fn(),
}));

vi.mock("ra-core", () => ({
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  EditBase: ({ children }: { children: ReactNode }) => <>{children}</>,
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
        // react-hook-form submits record defaults plus registered inputs.
        onSubmit({ ...project, name: "LG Display", is_active: true });
      }}
    >
      {children}
    </form>
  ),
  useDataProvider: () => ({ update: mocks.update }),
  useNotify: () => mocks.notify,
  useRecordContext: () => project,
  useRedirect: () => mocks.redirect,
}));

vi.mock("@/components/admin/text-input", () => ({
  TextInput: ({ label, className }: { label: string; className?: string }) => (
    <label className={className}>
      {label}
      <input />
    </label>
  ),
}));

vi.mock("@/components/admin/boolean-input", () => ({
  BooleanInput: ({
    label,
    className,
  }: {
    label: string;
    className?: string;
  }) => (
    <label className={className}>
      {label}
      <input type="checkbox" />
    </label>
  ),
}));

vi.mock("@/components/admin", () => ({
  DeleteButton: ({ label }: { label: string }) => <button>{label}</button>,
}));

vi.mock("../hooks/useRoleActions", () => ({
  useRoleActions: () => ({ isAdmin: true, canEdit: true }),
}));

vi.mock("./ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: () => <section>Kiến thức dự án</section>,
}));

vi.mock("./ProjectWorkspaceShell", () => ({
  ProjectWorkspaceShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));

import { ProjectEdit } from "./ProjectEdit";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

describe("ProjectEdit", () => {
  beforeEach(() => {
    mocks.update.mockReset().mockResolvedValue({ data: project });
    mocks.notify.mockReset();
    mocks.redirect.mockReset();
  });

  it("shows project identity once and keeps settings in one compact row", async () => {
    const screen = await render(<ProjectEdit />);

    await expect
      .element(screen.getByRole("heading", { name: "LG Display" }))
      .toBeVisible();
    await expect.element(screen.getByText("Đang hoạt động")).toBeVisible();
    await expect.element(screen.getByText("Theo danh mục")).toBeVisible();
    expect(
      screen.container.querySelector(".project-edit-settings"),
    ).not.toBeNull();
    expect(
      screen.container.querySelector(".project-form-section-header"),
    ).toBeNull();

    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

    await vi.waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith("projects", {
        id: "project-1",
        previousData: project,
        data: { name: "LG Display", is_active: true },
      });
      const updatePayload = mocks.update.mock.calls[0][1] as {
        data: Record<string, unknown>;
      };
      expect(Object.keys(updatePayload.data).sort()).toEqual([
        "is_active",
        "name",
      ]);
      expect(mocks.redirect).toHaveBeenCalledWith("/projects");
    });
  });
});
