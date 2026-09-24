import { type ReactNode } from "react";
import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeSource, Project } from "../types";
import "../conversations/inbox.css";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  redirect: vi.fn(),
  update: vi.fn(),
  source: {
    id: "source-a",
    drive_file_id: null,
    file_name: "Chính sách tuyển dụng.md",
    source: "upload",
    version: "1",
    status: "PUBLISHED",
    stage: "PUBLISHED",
    project_id: "project-a",
    project_name: "LG Display",
    mime_type: "text/markdown",
    digest_meta: { unit_count: 8 },
    created_at: "2026-07-22T00:00:00Z",
    updated_at: "2026-07-23T00:00:00Z",
  } as KnowledgeSource,
  project: {
    id: "project-a",
    name: "LG Display",
    slug: "lg-display",
    is_active: true,
    created_at: "2026-07-22T00:00:00Z",
    updated_at: "2026-07-23T00:00:00Z",
  } as Project,
}));

vi.mock("ra-core", () => ({
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  EditBase: ({ children }: { children: ReactNode }) => children,
  ShowBase: ({ children }: { children: ReactNode }) => children,
  useDataProvider: () => ({ update: mocks.update }),
  useGetOne: () => ({ data: mocks.project }),
  useNotify: () => mocks.notify,
  useRecordContext: () => mocks.source,
  useRedirect: () => mocks.redirect,
}));

vi.mock("./KnowledgeDetailPanel", () => ({
  KnowledgeDetailPanel: ({
    source,
    project,
    headingAs,
    headingId,
  }: {
    source: KnowledgeSource;
    project?: Project;
    headingAs?: string;
    headingId?: string;
  }) => (
    <section data-heading-as={headingAs}>
      <h1 id={headingId}>{source.file_name}</h1>
      <p>{project?.name}</p>
    </section>
  ),
}));

vi.mock("./ProjectPicker", () => ({
  ProjectPicker: ({
    id,
    value,
    onChange,
  }: {
    id?: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <select
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="project-a">LG Display</option>
      <option value="project-b">Rorze</option>
    </select>
  ),
}));

import { KnowledgeSourceEdit } from "./KnowledgeSourceEdit";
import { KnowledgeSourceShow } from "./KnowledgeSourceShow";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

describe("Knowledge source subpages", () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.redirect.mockReset();
    mocks.update.mockReset();
  });

  it("uses the shared content-first detail and a clear return action", async () => {
    const screen = await render(<KnowledgeSourceShow />);

    await expect
      .element(
        screen.getByRole("heading", {
          name: "Chính sách tuyển dụng.md",
          level: 1,
        }),
      )
      .toBeVisible();
    await expect.element(screen.getByText("LG Display")).toBeVisible();
    expect(screen.container.querySelector("[data-heading-as]")).toHaveAttribute(
      "data-heading-as",
      "h1",
    );
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
    expect(screen.container.querySelector("main")).toBeNull();

    await screen.getByRole("button", { name: "Tất cả nguồn" }).click();
    expect(mocks.redirect).toHaveBeenCalledWith("list", "knowledge_sources");
  });

  it("saves only meaningful changes and returns to the source detail", async () => {
    mocks.update.mockResolvedValue({ data: mocks.source });
    const screen = await render(<KnowledgeSourceEdit />);
    const name = screen.getByLabelText("Tên tài liệu");
    const project = screen.getByLabelText("Dự án");
    const save = screen.getByRole("button", { name: "Lưu thay đổi" });

    await expect.element(name).toHaveValue("Chính sách tuyển dụng.md");
    await expect.element(project).toHaveValue("project-a");
    await expect.element(save).toBeDisabled();
    expect(screen.container.querySelector("[data-slot='card']")).toBeNull();
    expect(screen.container.querySelector("main")).toBeNull();

    await name.fill("  Chính sách tuyển dụng 2026.md  ");
    await project.selectOptions("project-b");
    await expect.element(save).toBeEnabled();
    await save.click();

    await vi.waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith("knowledge_sources", {
        id: "source-a",
        previousData: mocks.source,
        data: {
          file_name: "Chính sách tuyển dụng 2026.md",
          project_id: "project-b",
        },
      });
    });
    expect(mocks.notify).toHaveBeenCalledWith("Đã lưu thay đổi.", {
      type: "success",
    });
    expect(mocks.redirect).toHaveBeenCalledWith(
      "show",
      "knowledge_sources",
      "source-a",
    );
  });

  it("keeps save disabled while a request is pending", async () => {
    let resolveUpdate: ((value: { data: KnowledgeSource }) => void) | undefined;
    mocks.update.mockImplementation(
      () =>
        new Promise<{ data: KnowledgeSource }>((resolve) => {
          resolveUpdate = resolve;
        }),
    );
    const screen = await render(<KnowledgeSourceEdit />);
    await screen
      .getByLabelText("Tên tài liệu")
      .fill("Chính sách tuyển dụng mới.md");
    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

    const pending = screen.getByRole("button", { name: "Đang lưu…" });
    await expect.element(pending).toBeDisabled();
    expect(mocks.update).toHaveBeenCalledTimes(1);

    resolveUpdate?.({ data: mocks.source });
    await vi.waitFor(() => {
      expect(mocks.notify).toHaveBeenCalledWith("Đã lưu thay đổi.", {
        type: "success",
      });
    });
  });

  it("offers explicit cancel without saving", async () => {
    const screen = await render(<KnowledgeSourceEdit />);
    await screen.getByRole("button", { name: "Hủy" }).click();

    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.redirect).toHaveBeenCalledWith(
      "show",
      "knowledge_sources",
      "source-a",
    );
  });
});
