import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/components/atomic-crm/providers/rest/api";
import type { KnowledgeCategoryStatus } from "@/lib/vfic/knowledgeService";
import type * as KnowledgeServiceModule from "@/lib/vfic/knowledgeService";
import type { Project } from "../types";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  refresh: vi.fn(),
  getProjectKnowledgeCategories: vi.fn(),
  getProjectKnowledgeCategorySource: vi.fn(),
  getProjectKnowledgeCategoryTemplate: vi.fn(),
  getProjectSinglePage: vi.fn(),
  listSinglePageExternalSources: vi.fn(),
  createSinglePageExternalSource: vi.fn(),
  runSinglePageExternalSourceNow: vi.fn(),
  deleteSinglePageExternalSource: vi.fn(),
  replaceProjectSinglePage: vi.fn(),
  uploadProjectKnowledgeCategory: vi.fn(),
  listExternalSources: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useDataProvider: () => ({ update: vi.fn() }),
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));

vi.mock("@/lib/vfic/knowledgeService", async (importOriginal) => ({
  ...(await importOriginal<typeof KnowledgeServiceModule>()),
  getProjectKnowledgeCategories: mocks.getProjectKnowledgeCategories,
  getProjectKnowledgeCategorySource: mocks.getProjectKnowledgeCategorySource,
  getProjectKnowledgeCategoryTemplate:
    mocks.getProjectKnowledgeCategoryTemplate,
  getProjectSinglePage: mocks.getProjectSinglePage,
  listSinglePageExternalSources: mocks.listSinglePageExternalSources,
  createSinglePageExternalSource: mocks.createSinglePageExternalSource,
  runSinglePageExternalSourceNow: mocks.runSinglePageExternalSourceNow,
  deleteSinglePageExternalSource: mocks.deleteSinglePageExternalSource,
  replaceProjectSinglePage: mocks.replaceProjectSinglePage,
  uploadProjectKnowledgeCategory: mocks.uploadProjectKnowledgeCategory,
  listExternalSources: mocks.listExternalSources,
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

const singlePageProject: Project = {
  ...project,
  id: "project-rorze",
  name: "Rorze",
  slug: "rorze",
  is_active: false,
  knowledge_mode: "DIRECT_CONTEXT",
  index_card: {
    summary: "Rorze tuyển nhân viên vận hành máy CNC",
    location: "KCN Nomura, Hải Phòng",
  },
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
    mocks.listSinglePageExternalSources.mockResolvedValue([]);
    mocks.listExternalSources.mockResolvedValue([]);
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

  it("refreshes the inactive project after its first valid single-page save", async () => {
    mocks.getProjectSinglePage.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    mocks.replaceProjectSinglePage.mockResolvedValue({
      id: "direct-file-rorze",
      filename: "single-page.md",
    });

    const screen = await render(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    const editor = screen.getByLabelText("Nội dung trang kiến thức");
    await expect.element(editor).toBeVisible();
    await editor.fill("Rorze tuyển nhân viên vận hành máy CNC.");
    await screen.getByRole("button", { name: "Lưu trang kiến thức" }).click();

    await vi.waitFor(() => {
      expect(mocks.replaceProjectSinglePage).toHaveBeenCalledWith(
        "project-rorze",
        "single-page.md",
        "Rorze tuyển nhân viên vận hành máy CNC.",
      );
      expect(mocks.refresh).toHaveBeenCalledTimes(1);
    });
  });

  it("warns before replacing a page that will reactivate an inactive project", async () => {
    mocks.getProjectSinglePage.mockResolvedValue({
      id: "direct-file-rorze",
      knowledge_base_id: "kb-rorze",
      filename: "rorze.md",
      text: "Nội dung Rorze hiện tại.",
      char_count: 24,
      line_count: 1,
      content_sha256: "checksum",
      updated_at: "2026-07-18T00:00:00Z",
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    const screen = await render(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    await expect
      .element(screen.getByLabelText("Nội dung trang kiến thức"))
      .toHaveValue("Nội dung Rorze hiện tại.");
    await screen
      .getByRole("button", { name: "Thay thế trang hiện tại" })
      .click();

    expect(confirm).toHaveBeenCalledWith(
      "Nội dung mới sẽ thay thế toàn bộ trang hiện tại và bật dự án để Agent sử dụng. Tiếp tục?",
    );
    expect(mocks.replaceProjectSinglePage).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("shows the overwrite warning when a single-page auto-sync source is active", async () => {
    mocks.getProjectSinglePage.mockResolvedValue({
      id: "single-page-1",
      knowledge_base_id: "kb-1",
      filename: "single-page.md",
      text: "Nội dung hiện tại",
      char_count: 17,
      line_count: 1,
      content_sha256: "sha",
      updated_at: "2026-07-22T00:00:00Z",
    });
    mocks.listSinglePageExternalSources.mockResolvedValue([
      {
        id: "src-sp-1",
        project_id: "project-rorze",
        source_kind: "google_sheet",
        sheet_url: "https://docs.google.com/spreadsheets/d/demo/edit#gid=42",
        sheet_gid: 42,
        auto_sync_enabled: true,
        consecutive_failures: 0,
        last_status: "OK",
        created_at: "2026-07-22T00:00:00Z",
        updated_at: "2026-07-22T00:00:00Z",
      },
    ]);

    const screen = await render(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );

    await expect
      .element(
        screen.getByText("Đồng bộ tự động có thể ghi đè chỉnh sửa tay"),
      )
      .toBeVisible();
  });

  it("ignores an older single-page refresh response after a newer one wins", async () => {
    let singlePageSourceCalls = 0;
    const firstRefresh = deferred<{
      id: string;
      knowledge_base_id: string;
      filename: string;
      text: string;
      char_count: number;
      line_count: number;
      content_sha256: string;
      updated_at: string;
    }>();
    const secondRefresh = deferred<{
      id: string;
      knowledge_base_id: string;
      filename: string;
      text: string;
      char_count: number;
      line_count: number;
      content_sha256: string;
      updated_at: string;
    }>();
    mocks.listSinglePageExternalSources.mockImplementation(() => {
      singlePageSourceCalls += 1;
      if (singlePageSourceCalls < 3) {
        return Promise.resolve([]);
      }
      return Promise.resolve([
        {
          id: "src-sp-1",
          project_id: "project-rorze",
          source_kind: "google_sheet",
          sheet_url: "https://docs.google.com/spreadsheets/d/demo/edit#gid=42",
          sheet_gid: 42,
          auto_sync_enabled: false,
          consecutive_failures: 0,
          last_status: "OK",
          last_synced_at: "2026-07-22T00:04:00Z",
          created_at: "2026-07-22T00:04:00Z",
          updated_at: "2026-07-22T00:04:00Z",
        },
      ]);
    });

    mocks.getProjectSinglePage
      .mockResolvedValueOnce({
        id: "single-page-1",
        knowledge_base_id: "kb-1",
        filename: "single-page.md",
        text: "Nội dung ban đầu",
        char_count: 15,
        line_count: 1,
        content_sha256: "sha-1",
        updated_at: "2026-07-22T00:00:00Z",
      })
      .mockImplementationOnce(() => firstRefresh.promise)
      .mockImplementationOnce(() => secondRefresh.promise);

    const screen = await render(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );

    const editor = screen.getByLabelText("Nội dung trang kiến thức");
    await expect.element(editor).toHaveValue("Nội dung ban đầu");

    const refreshButton = screen.getByRole("button", {
      name: "Làm mới nội dung",
    });
    await refreshButton.click();

    secondRefresh.resolve({
      id: "single-page-1",
      knowledge_base_id: "kb-1",
      filename: "single-page.md",
      text: "Bản mới nhất",
      char_count: 11,
      line_count: 1,
      content_sha256: "sha-3",
      updated_at: "2026-07-22T00:03:00Z",
    });
    await vi.waitFor(() =>
      expect(screen.getByLabelText("Nội dung trang kiến thức").element()).toHaveValue(
        "Bản mới nhất",
      ),
    );

    firstRefresh.resolve({
      id: "single-page-1",
      knowledge_base_id: "kb-1",
      filename: "single-page.md",
      text: "Phản hồi cũ",
      char_count: 11,
      line_count: 1,
      content_sha256: "sha-2",
      updated_at: "2026-07-22T00:02:00Z",
    });

    await vi.waitFor(() =>
      expect(screen.getByLabelText("Nội dung trang kiến thức").element()).toHaveValue(
        "Bản mới nhất",
      ),
    );
  });

  it("keeps sync status visible but hides mutations in single-page read-only mode", async () => {
    mocks.getProjectSinglePage.mockResolvedValue({
      id: "single-page-1",
      knowledge_base_id: "kb-1",
      filename: "single-page.md",
      text: "Nội dung hiện tại",
      char_count: 17,
      line_count: 1,
      content_sha256: "sha",
      updated_at: "2026-07-22T00:00:00Z",
    });
    mocks.listSinglePageExternalSources.mockResolvedValue([
      {
        id: "src-sp-1",
        project_id: "project-rorze",
        source_kind: "google_sheet",
        sheet_url: "https://docs.google.com/spreadsheets/d/demo/edit#gid=42",
        sheet_gid: 42,
        auto_sync_enabled: false,
        consecutive_failures: 0,
        last_status: "NO_OP",
        created_at: "2026-07-22T00:00:00Z",
        updated_at: "2026-07-22T00:00:00Z",
      },
    ]);

    const screen = await render(
      <ProjectKnowledgePanel project={singlePageProject} editable={false} />,
    );

    await expect
      .element(screen.getByText("Đồng bộ Google Sheet 1 trang"))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("Liên kết Google Sheet");
    expect(screen.container.textContent).not.toContain("Xử lý ngay");
    expect(screen.container.textContent).not.toContain("Thay thế trang hiện tại");
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
