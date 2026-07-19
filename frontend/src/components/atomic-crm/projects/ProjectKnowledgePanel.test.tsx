import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/components/atomic-crm/providers/rest/api";
import type { KnowledgeCategoryStatus } from "@/lib/vfic/knowledgeService";
import type { Project } from "../types";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  getProjectKnowledgeCategories: vi.fn(),
  getProjectKnowledgeCategorySource: vi.fn(),
  getProjectKnowledgeCategoryTemplate: vi.fn(),
  getProjectSinglePage: vi.fn(),
  replaceProjectSinglePage: vi.fn(),
  uploadProjectKnowledgeCategory: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useDataProvider: () => ({ update: vi.fn() }),
  useNotify: () => mocks.notify,
  useRefresh: () => vi.fn(),
}));

vi.mock("@/lib/vfic/knowledgeService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/vfic/knowledgeService")>()),
  getProjectKnowledgeCategories: mocks.getProjectKnowledgeCategories,
  getProjectKnowledgeCategorySource: mocks.getProjectKnowledgeCategorySource,
  getProjectKnowledgeCategoryTemplate:
    mocks.getProjectKnowledgeCategoryTemplate,
  getProjectSinglePage: mocks.getProjectSinglePage,
  replaceProjectSinglePage: mocks.replaceProjectSinglePage,
  uploadProjectKnowledgeCategory: mocks.uploadProjectKnowledgeCategory,
}));

import { ProjectKnowledgePanel } from "./ProjectKnowledgePanel";

const project: Project = {
  id: "project-1",
  name: "LG Display",
  slug: "lg-display",
  is_active: true,
  knowledge_mode: "RAG",
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
};

const categories: KnowledgeCategoryStatus[] = [
  {
    key: "jobs",
    label_vi: "Vị trí tuyển dụng",
    active_revision_id: "revision-jobs",
    active_revision_no: 2,
    status: "ACTIVE",
  },
  {
    key: "compensation",
    label_vi: "Lương & thu nhập",
    active_revision_id: null,
    status: null,
  },
];

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

describe("ProjectKnowledgePanel", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.getProjectKnowledgeCategories.mockResolvedValue({
      data: categories,
      total: categories.length,
    });
    mocks.getProjectKnowledgeCategoryTemplate.mockImplementation(
      (_projectId: string, key: string) =>
        Promise.resolve({
          key,
          label_vi: key,
          filename: `${key}-template.yaml`,
          content: `TEMPLATE ${key}`,
        }),
    );
  });

  it("shows current category data and keeps the template behind the download action", async () => {
    mocks.getProjectKnowledgeCategorySource.mockImplementation(
      (_projectId: string, key: string) => {
        if (key === "jobs") {
          return Promise.resolve({
            key,
            label_vi: "Vị trí tuyển dụng",
            revision_id: "revision-jobs",
            revision_no: 2,
            filename: "jobs-current.yaml",
            content: "CURRENT JOBS",
            checksum: "checksum",
            updated_at: "2026-07-18T00:00:00Z",
          });
        }
        return Promise.reject(new ApiError(404, "Chưa có dữ liệu"));
      },
    );

    const screen = await render(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const jobsEditor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
    );
    await expect.element(jobsEditor).toHaveValue("CURRENT JOBS");
    await expect.element(jobsEditor).toHaveAttribute("readonly");
    expect(screen.container.textContent).not.toContain(
      "Kiểm tra và thay thế mục này",
    );
    expect(screen.container.textContent).not.toContain("Xóa dữ liệu mục");
    await expect
      .element(screen.getByRole("button", { name: "Tải file YAML" }))
      .toBeVisible();
    await expect
      .element(
        screen.getByText(
          "Dữ liệu hiện tại Agent đang sử dụng · jobs-current.yaml",
        ),
      )
      .toBeVisible();

    await screen.getByRole("button", { name: "Lương & thu nhập" }).click();

    const emptyEditor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Lương & thu nhập",
    );
    await expect.element(emptyEditor).toHaveValue("");
    expect(screen.container.textContent).not.toContain("TEMPLATE compensation");
    await expect
      .element(screen.getByRole("button", { name: "Tải mẫu" }))
      .toBeEnabled();
    expect(
      screen.container.querySelector(
        '.project-category-editor-heading [data-slot="badge"]',
      )?.textContent,
    ).toBe("Chưa có dữ liệu");
  });

  it("ignores a late response from a previously selected category", async () => {
    const lateJobs = deferred<{
      key: string;
      label_vi: string;
      revision_id: string;
      revision_no: number;
      filename: string;
      content: string;
      checksum: string;
      updated_at: string;
    }>();
    mocks.getProjectKnowledgeCategorySource.mockImplementation(
      (_projectId: string, key: string) => {
        if (key === "jobs") return lateJobs.promise;
        return Promise.resolve({
          key,
          label_vi: "Lương & thu nhập",
          revision_id: "revision-compensation",
          revision_no: 1,
          filename: "compensation-current.yaml",
          content: "CURRENT COMPENSATION",
          checksum: "checksum",
          updated_at: "2026-07-18T00:00:00Z",
        });
      },
    );

    const screen = await render(
      <ProjectKnowledgePanel project={project} editable />,
    );
    await screen.getByRole("button", { name: "Lương & thu nhập" }).click();

    const compensationEditor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Lương & thu nhập",
    );
    await expect
      .element(compensationEditor)
      .toHaveValue("CURRENT COMPENSATION");

    lateJobs.resolve({
      key: "jobs",
      label_vi: "Vị trí tuyển dụng",
      revision_id: "revision-jobs",
      revision_no: 2,
      filename: "jobs-current.yaml",
      content: "LATE JOBS RESPONSE",
      checksum: "checksum",
      updated_at: "2026-07-18T00:00:00Z",
    });

    await vi.waitFor(() => {
      expect(screen.container.textContent).not.toContain("LATE JOBS RESPONSE");
    });
    await expect
      .element(compensationEditor)
      .toHaveValue("CURRENT COMPENSATION");
  });
});
