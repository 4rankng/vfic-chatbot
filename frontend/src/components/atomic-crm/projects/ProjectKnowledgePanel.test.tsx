import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";
import { render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/apiClient";
import type { KnowledgeCategoryStatus } from "./project-knowledge-service";
import type * as KnowledgeServiceModule from "./project-knowledge-service";
import type { Project } from "../types";
import "./projects.css";

let queryClient: QueryClient;

/** The panel's external-source rows read their query from the app's client. */
const QueryClientWrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

const renderPanel = (ui: ReactElement) =>
  render(ui, { wrapper: QueryClientWrapper });

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
  replaceProjectKnowledgeCategory: vi.fn(),
  uploadProjectKnowledgeCategory: vi.fn(),
  listExternalSources: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useDataProvider: () => ({ update: vi.fn() }),
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));

vi.mock("./project-knowledge-service", async (importOriginal) => ({
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
  replaceProjectKnowledgeCategory: mocks.replaceProjectKnowledgeCategory,
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
  afterEach(async () => {
    vi.restoreAllMocks();
    await page.viewport(1280, 720);
  });

  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
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

    const screen = await renderPanel(
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

  it("stacks and bounds the single-page editor on phone screens", async () => {
    await page.viewport(390, 844);
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

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    const editor = screen.getByLabelText("Nội dung trang kiến thức");
    await expect.element(editor).toBeVisible();

    const title = screen.container.querySelector(".project-single-page-title");
    const fileRow = screen.container.querySelector(
      ".project-single-page-file-row",
    );
    const saveButton = screen
      .getByRole("button", {
        name: "Thay thế trang hiện tại",
      })
      .element();

    expect(title).toBeInstanceOf(HTMLElement);
    expect(fileRow).toBeInstanceOf(HTMLElement);
    expect(window.getComputedStyle(title as HTMLElement).flexDirection).toBe(
      "column",
    );
    expect(window.getComputedStyle(fileRow as HTMLElement).display).toBe(
      "grid",
    );
    expect(editor.element().getBoundingClientRect().height).toBeLessThanOrEqual(
      390,
    );
    expect(saveButton.getBoundingClientRect().width).toBeGreaterThan(300);
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

    const screen = await renderPanel(
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

  it("shows the sync flow and progressively discloses the overwrite warning", async () => {
    await page.viewport(390, 844);
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

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );

    await expect
      .element(screen.getByText("Google Sheet", { exact: true }))
      .toBeVisible();
    // Auto-sync state now surfaces via the source-row badge, not the flow
    // diagram caption (which was removed to cut visual noise).
    await expect
      .element(screen.getByLabelText("Tự động mỗi ngày"))
      .toBeVisible();
    await expect
      .element(screen.getByText("Trang kiến thức", { exact: true }))
      .toBeVisible();
    const syncHeading = screen.container.querySelector(
      "#single-page-sync-heading",
    )!;
    expect(syncHeading.parentElement?.querySelector("svg")).not.toBeNull();
    expect(syncHeading.parentElement?.className).toContain("inline-flex");
    expect(syncHeading.parentElement?.className).toContain("whitespace-nowrap");

    const warning = screen.getByText("Sheet sẽ ghi đè nội dung sửa tay");
    const warningDetail = screen.getByText(
      "Khi lịch hàng ngày đang bật, dữ liệu mới từ Google Sheet sẽ thay thế nội dung sửa thủ công ở lần đồng bộ tiếp theo.",
    );
    await expect.element(warning).toBeVisible();
    await expect.element(warningDetail).not.toBeVisible();
    const warningCallout = warning.element().closest("details");
    expect(warningCallout?.className).toContain("text-foreground");
    expect(warningCallout?.className).not.toContain("text-warning-foreground");

    await warning.click();

    await expect.element(warningDetail).toBeVisible();
  });

  it("ignores an older single-page refresh response after a newer one wins", async () => {
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

    // Without the manual "Nạp lại" button, overlapping single-page reloads are
    // driven by ExternalSourceList's onSynchronized callback, which fires each
    // time a sync signature changes. Each list call returns a row with a fresh
    // signature so every post-runNow poll fires onSynchronized → loadPage.
    let sourceCall = 0;
    mocks.listSinglePageExternalSources.mockImplementation(() => {
      sourceCall += 1;
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
          last_content_hash: `h${sourceCall}`,
          last_synced_at: `2026-07-22T00:0${sourceCall}:00Z`,
          created_at: "2026-07-22T00:00:00Z",
          updated_at: `2026-07-22T00:0${sourceCall}:00Z`,
        },
      ]);
    });
    mocks.runSinglePageExternalSourceNow.mockResolvedValue({ job_id: "job-1" });

    mocks.getProjectSinglePage
      // mount loadPage (non-background) → editor becomes interactive
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
      // onSynchronized #1 → the older in-flight request
      .mockImplementationOnce(() => firstRefresh.promise)
      // onSynchronized #2 → the newer in-flight request
      .mockImplementationOnce(() => secondRefresh.promise);

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );

    await expect
      .element(screen.getByLabelText("Nội dung trang kiến thức"))
      .toHaveValue("Nội dung ban đầu");

    vi.useFakeTimers();

    // First sync completion → onSynchronized → loadPage (firstRefresh, pending).
    await screen.getByRole("button", { name: "Đồng bộ ngay" }).click();
    await vi.advanceTimersByTimeAsync(4000);

    // Clear the 5-minute run-now cooldown before triggering a second sync.
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    await screen.getByRole("button", { name: "Đồng bộ ngay" }).click();
    await vi.advanceTimersByTimeAsync(4000);

    // Newer request resolves first → its content is applied.
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
      expect(
        screen.getByLabelText("Nội dung trang kiến thức").element(),
      ).toHaveValue("Bản mới nhất"),
    );

    // Older request resolves after → discarded by loadPage's request guard.
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
      expect(
        screen.getByLabelText("Nội dung trang kiến thức").element(),
      ).toHaveValue("Bản mới nhất"),
    );
  });

  it("does not request admin-only sync state in single-page read-only mode", async () => {
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

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable={false} />,
    );

    expect(mocks.listSinglePageExternalSources).not.toHaveBeenCalled();
    expect(screen.container.textContent).not.toContain(
      "Google Sheet → trang kiến thức",
    );
    expect(screen.container.textContent).not.toContain("Liên kết Google Sheet");
    expect(
      screen.container.querySelector(".project-external-source-actions"),
    ).toBeNull();
    expect(screen.container.textContent).not.toContain(
      "Thay thế trang hiện tại",
    );
  });

  it("does not refetch sync state while an admin edits page text", async () => {
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
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(2),
    );

    await screen
      .getByLabelText("Nội dung trang kiến thức")
      .fill("Nội dung đang chỉnh sửa");

    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(2),
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

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const jobsEditor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
    );
    await expect.element(jobsEditor).toHaveValue("CURRENT JOBS");
    await expect.element(jobsEditor).toHaveAttribute("readonly");
    await expect.element(jobsEditor).not.toBeVisible();
    await screen
      .getByLabelText("Xem dữ liệu danh mục Vị trí tuyển dụng")
      .click();
    await expect.element(jobsEditor).toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Sửa nội dung" }))
      .toBeVisible();
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

    expect(
      screen.container.querySelector(
        '[aria-label="Xem dữ liệu danh mục Lương & thu nhập"]',
      ),
    ).toBeNull();
    expect(
      screen.container.querySelector(
        '[aria-label="Dữ liệu hiện tại của danh mục Lương & thu nhập"]',
      ),
    ).toBeNull();
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

  it("lets an authorized editor save YAML manually through the review pipeline", async () => {
    mocks.getProjectKnowledgeCategorySource.mockResolvedValue({
      key: "jobs",
      label_vi: "Vị trí tuyển dụng",
      revision_id: "revision-jobs",
      revision_no: 2,
      filename: "jobs-current.yaml",
      content: "jobs:\n  - id: old",
      checksum: "checksum",
      updated_at: "2026-07-18T00:00:00Z",
    });
    mocks.replaceProjectKnowledgeCategory.mockResolvedValue({
      revision: { id: "revision-new" },
      job_id: "job-new",
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    const screen = await renderPanel(
      <ProjectKnowledgePanel
        project={project}
        editable
        canManageSources={false}
      />,
    );
    const editor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
    );

    await screen.getByRole("button", { name: "Sửa nội dung" }).click();
    await expect.element(editor).not.toHaveAttribute("readonly");
    const saveButton = screen.getByRole("button", { name: "Lưu thay đổi" });
    await expect.element(saveButton).toBeDisabled();
    expect(saveButton.element().className).toContain(
      "project-category-save-button",
    );
    await editor.fill("jobs:\n  - id: operator");
    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

    await vi.waitFor(() => {
      expect(mocks.replaceProjectKnowledgeCategory).toHaveBeenCalledWith(
        "project-1",
        "jobs",
        "jobs-current.yaml",
        "jobs:\n  - id: operator",
      );
    });
    expect(confirm).toHaveBeenCalledWith(
      "Nội dung đã sửa sẽ tạo phiên bản mới và thay thế dữ liệu đang dùng sau khi kiểm tra. Tiếp tục?",
    );
    await expect.element(editor).toHaveAttribute("readonly");
    await expect
      .element(screen.getByRole("button", { name: "Sửa nội dung" }))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("Tải file YAML");
    expect(screen.container.textContent).not.toContain("Sync From Link");
    expect(mocks.listExternalSources).not.toHaveBeenCalled();
  });

  it("restores the current YAML when manual editing is cancelled", async () => {
    mocks.getProjectKnowledgeCategorySource.mockResolvedValue({
      key: "jobs",
      label_vi: "Vị trí tuyển dụng",
      revision_id: "revision-jobs",
      revision_no: 2,
      filename: "jobs-current.yaml",
      content: "CURRENT JOBS",
      checksum: "checksum",
      updated_at: "2026-07-18T00:00:00Z",
    });

    const screen = await renderPanel(
      <ProjectKnowledgePanel
        project={project}
        editable
        canManageSources={false}
      />,
    );
    const editor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
    );

    await screen.getByRole("button", { name: "Sửa nội dung" }).click();
    await editor.fill("UNSAVED CONTENT");
    await screen.getByRole("button", { name: "Hủy" }).click();

    await expect.element(editor).toHaveValue("CURRENT JOBS");
    await expect.element(editor).toHaveAttribute("readonly");
    expect(mocks.replaceProjectKnowledgeCategory).not.toHaveBeenCalled();
  });

  it("stacks the selected category detail below the list in the phone viewport", async () => {
    await page.viewport(390, 844);
    mocks.getProjectKnowledgeCategorySource.mockResolvedValue({
      key: "jobs",
      label_vi: "Vị trí tuyển dụng",
      revision_id: "revision-jobs",
      revision_no: 2,
      filename: "jobs-current.yaml",
      content: "CURRENT JOBS",
      checksum: "checksum",
      updated_at: "2026-07-18T00:00:00Z",
    });

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );
    await expect
      .element(
        screen.getByLabelText(
          "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
        ),
      )
      .not.toBeVisible();
    await screen
      .getByLabelText("Xem dữ liệu danh mục Vị trí tuyển dụng")
      .click();
    await expect
      .element(
        screen.getByLabelText(
          "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
        ),
      )
      .toBeVisible();

    const workspace = screen.container.querySelector(
      ".project-category-workspace",
    );
    const navigation = screen.container.querySelector(
      ".project-category-navigation",
    );
    const mobileSelector = screen.getByLabelText("Chọn danh mục kiến thức");
    const detail = screen.container.querySelector("#project-category-detail");
    expect(workspace).toBeInstanceOf(HTMLElement);
    expect(navigation).toBeInstanceOf(HTMLElement);
    expect(detail).toBeInstanceOf(HTMLElement);

    const workspaceStyle = window.getComputedStyle(workspace as HTMLElement);
    const navigationBounds = (
      navigation as HTMLElement
    ).getBoundingClientRect();
    const detailBounds = (detail as HTMLElement).getBoundingClientRect();
    await expect.element(mobileSelector).toBeVisible();
    expect(workspaceStyle.display).toBe("block");
    expect(detailBounds.top).toBeGreaterThanOrEqual(navigationBounds.bottom);
    expect(detailBounds.left).toBe(navigationBounds.left);
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

    const screen = await renderPanel(
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

  it("brings the selected category detail into focus on a small screen", async () => {
    mocks.getProjectKnowledgeCategorySource.mockImplementation(
      (_projectId: string, key: string) =>
        Promise.resolve({
          key,
          label_vi: key === "jobs" ? "Vị trí tuyển dụng" : "Lương & thu nhập",
          revision_id: `revision-${key}`,
          revision_no: 1,
          filename: `${key}-current.yaml`,
          content: `CURRENT ${key}`,
          checksum: "checksum",
          updated_at: "2026-07-18T00:00:00Z",
        }),
    );
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) =>
        ({
          matches: query === "(max-width: 767px)",
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(() => true),
        }) as MediaQueryList,
    );
    const scrollIntoView = vi
      .spyOn(HTMLElement.prototype, "scrollIntoView")
      .mockImplementation(() => undefined);

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );
    await screen.getByRole("button", { name: "Lương & thu nhập" }).click();

    await vi.waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({
        behavior: "smooth",
        block: "start",
      });
    });
    expect(document.activeElement).toBe(
      screen.container.querySelector("#project-category-detail"),
    );
  });
});
