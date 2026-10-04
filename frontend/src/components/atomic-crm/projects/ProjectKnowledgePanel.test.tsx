import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type * as RaCore from "ra-core";
import type { ReactElement, ReactNode } from "react";
import { render } from "vitest-browser-react";
import { page, userEvent } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/apiClient";
import type { KnowledgeCategoryStatus } from "./project-knowledge-service";
import type * as KnowledgeServiceModule from "./project-knowledge-service";
import type { Project } from "../types";
import "@/index.css";
import "./projects.css";

let queryClient: QueryClient;

/** The panel's external-source rows read their query from the app's client. */
const QueryClientWrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>
    <div className="inbox-bg-container project-workspace">{children}</div>
  </QueryClientProvider>
);

const renderPanel = (ui: ReactElement) =>
  render(ui, { wrapper: QueryClientWrapper });

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  refresh: vi.fn(),
  getProjectKnowledgeCategories: vi.fn(),
  getProjectKnowledgeCategorySource: vi.fn(),
  getProjectKnowledgeCategoryTemplate: vi.fn(),
  getProjectKnowledgeExport: vi.fn(),
  getProjectSinglePage: vi.fn(),
  replaceProjectSinglePage: vi.fn(),
  replaceProjectKnowledgeCategory: vi.fn(),
  /** The migration's explicit empty state for a brief-carried gap. */
  clearProjectKnowledgeCategory: vi.fn(),
  /** The migration's final authority hand-over. */
  cutoverProjectKnowledgeCategories: vi.fn(),
  /** The brief file's upload to the project document shelf. */
  uploadProjectDocument: vi.fn(),
  getProjectTrainingDocument: vi.fn(),
  /** The brief's highlights PATCHed onto the discovery card. */
  updateProjectDiscoveryCard: vi.fn(),
}));

vi.mock("ra-core", async (importOriginal) => ({
  // The component under test reads its labels from the Vietnamese catalog.
  ...(await importOriginal<typeof RaCore>()),
  useTranslate: () => testI18nProvider.translate,
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
  getProjectKnowledgeExport: mocks.getProjectKnowledgeExport,
  getProjectSinglePage: mocks.getProjectSinglePage,
  replaceProjectSinglePage: mocks.replaceProjectSinglePage,
  replaceProjectKnowledgeCategory: mocks.replaceProjectKnowledgeCategory,
  clearProjectKnowledgeCategory: mocks.clearProjectKnowledgeCategory,
  cutoverProjectKnowledgeCategories: mocks.cutoverProjectKnowledgeCategories,
  uploadProjectDocument: mocks.uploadProjectDocument,
  getProjectTrainingDocument: mocks.getProjectTrainingDocument,
  updateProjectDiscoveryCard: mocks.updateProjectDiscoveryCard,
}));

import { ProjectKnowledgePanel } from "./ProjectKnowledgePanel";
import { parseProjectBrief } from "./domain/project-brief-ingest";
import { planBriefKnowledge } from "./domain/project-knowledge-markdown";
import { PROJECT_KNOWLEDGE_CATEGORIES } from "./domain/project-knowledge-policy";

/** Provider receipt fixture; browser previews are never submitted as plans. */
let backendWrites: ReturnType<typeof planBriefKnowledge>["writes"] = [];
// The real recruiter brief the ingestion contract is proven against.
import amtranBrief from "./domain/fixtures/amtran-vsip-hai-phong.md?raw";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

const project: Project = {
  id: "project-1",
  name: "LG Display",
  slug: "lg-display",
  is_active: true,
  knowledge_mode: "RAG",
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
};

const plannedWrites = () => backendWrites;

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
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
};

/** The recruiter brief shape — an overview table plus Q&A sections — that
 *  carries exactly the jobs, compensation and faq categories the re-ingest
 *  tests below expect the full write set for. */
const REUPLOAD_BRIEF = `# PHIẾU THU THẬP
| **Tên dự án tuyển dụng** | 4P ELECTRONIC |
| **Tên viết tắt / Tên thường gọi** | 4P Electronics / 4P Hải Phòng |
| **Địa chỉ nơi làm việc** | Tầng 2 LGE, KCN Tràng Duệ, An Phong, TP. Hải Phòng |
| **Vị trí tuyển dụng chính** | Công nhân (SMT, PCBA) |
| **Tóm tắt công việc** | Lắp ráp linh kiện bảng mạch. |
| **Các điểm nổi bật thu hút** | - Không yêu cầu bằng cấp.<br>- Đóng BHXH đầy đủ. |

### 1. Vị trí tuyển dụng & Công việc cụ thể
* **Câu hỏi thường gặp:**
  * Công ty tuyển việc gì?
* **Thông tin phản hồi:**
  * **Vị trí tuyển:** Công nhân sản xuất.

### 3. Tiền lương, phụ cấp & Tăng ca
* **Câu hỏi thường gặp:**
  * Lương bao nhiêu?
* **Thông tin phản hồi:**
  * **Lương cơ bản:** 6.200.000 đồng/tháng.
`;

/** The same brief with its highlights row removed: a re-ingest of a file
 *  carrying no "Các điểm nổi bật" facts must send no discovery-card patch. */
const NO_HIGHLIGHTS_BRIEF = REUPLOAD_BRIEF.replace(
  /^.*Các điểm nổi bật.*\n/gm,
  "",
);

describe("ProjectKnowledgePanel", () => {
  it.each([project, singlePageProject])(
    "offers saved knowledge export to an administrator in $knowledge_mode",
    async (record) => {
      const screen = await renderPanel(
        <ProjectKnowledgePanel project={record} editable canManageSources />,
      );
      await expect
        .element(screen.getByRole("button", { name: "Xuất KB" }))
        .toBeVisible();
      await expect
        .element(screen.getByText("KB đang sử dụng · Markdown (.md)"))
        .toBeVisible();
      expect(mocks.getProjectKnowledgeExport).not.toHaveBeenCalled();
    },
  );

  it.each([project, singlePageProject])(
    "keeps export unavailable to a recruiter in $knowledge_mode",
    async (record) => {
      const screen = await renderPanel(
        <ProjectKnowledgePanel
          project={record}
          editable
          canManageSources={false}
        />,
      );
      await expect
        .element(screen.getByRole("button", { name: "Xuất KB" }))
        .not.toBeInTheDocument();
      expect(mocks.getProjectKnowledgeExport).not.toHaveBeenCalled();
    },
  );

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
    mocks.getProjectKnowledgeCategorySource.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    backendWrites = [];
    mocks.uploadProjectDocument.mockImplementation(
      async (_id: string, file: File) => {
        backendWrites = planBriefKnowledge(
          parseProjectBrief(await file.text()),
        ).writes;
        return { id: "training-document" };
      },
    );
    mocks.getProjectTrainingDocument.mockImplementation(async () => ({
      id: "training-document",
      status: "PUBLISHED",
      error: null,
      project_training: {
        status: "COMPLETED",
        current: null,
        completed: plannedWrites().map((write) => write.key),
        error: null,
      },
    }));
    mocks.clearProjectKnowledgeCategory.mockResolvedValue({
      id: "cleared-revision",
      category_id: "category-cleared",
      revision_no: 1,
      status: "CLEARED",
      source_filename: "cleared.yaml",
      content_sha256: "checksum",
      normalized_payload: {},
      created_at: "2026-07-18T00:00:00Z",
    });
    mocks.cutoverProjectKnowledgeCategories.mockResolvedValue({
      project_id: "project-1",
      category_authority_started: true,
      category_cutover_at: "2026-07-18T00:00:00Z",
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

  it("contains category status and date inside the compound navigation card", async () => {
    await page.viewport(1280, 900);
    mocks.getProjectKnowledgeCategories.mockResolvedValue({
      data: [
        {
          ...categories[0],
          status: "FAILED",
          updated_at: "2026-07-18T00:00:00Z",
        },
      ],
      total: 1,
    });
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );
    await expect
      .element(screen.getByText("Cập nhật lỗi — nội dung cũ vẫn đang dùng"))
      .toBeVisible();
    const card = screen.container.querySelector<HTMLElement>(
      ".project-category-card",
    )!;
    const date = card.querySelector<HTMLElement>(".project-category-date")!;
    const cardRect = card.getBoundingClientRect();
    expect(getComputedStyle(card).maxHeight).toBe("none");
    expect(date.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      cardRect.bottom - 10,
    );
  });

  it.each([null, undefined])(
    "keeps unusable editors hidden for legacy projects with mode %s",
    async (knowledge_mode) => {
      const screen = await renderPanel(
        <ProjectKnowledgePanel
          project={{ ...project, knowledge_mode }}
          editable
          canManageSources
        />,
      );
      await expect
        .element(
          screen.getByRole("heading", {
            name: "Kiến thức chưa được chuyển đổi",
          }),
        )
        .toBeVisible();
      await expect
        .element(screen.getByRole("button", { name: "Xuất KB" }))
        .toBeVisible();
      expect(mocks.getProjectKnowledgeCategories).not.toHaveBeenCalled();
      expect(mocks.getProjectKnowledgeCategorySource).not.toHaveBeenCalled();
      expect(mocks.getProjectSinglePage).not.toHaveBeenCalled();
      expect(
        screen.container.querySelector(".project-category-workspace"),
      ).toBeNull();
    },
  );

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

  it("opens the single-page file picker from the keyboard", async () => {
    mocks.getProjectSinglePage.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    const picker = screen.getByRole("button", { name: "Chọn file" });
    await expect.element(picker).toBeVisible();
    await expect.element(picker).toBeEnabled();
    const input = screen.container.querySelector<HTMLInputElement>(
      'input[aria-label="Chọn tệp trang kiến thức"]',
    )!;
    const open = vi.spyOn(input, "click").mockImplementation(() => undefined);
    picker.element().focus();
    await expect.element(picker).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await vi.waitFor(() => expect(open).toHaveBeenCalledTimes(1));
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
      "Nội dung mới sẽ thay thế toàn bộ trang hiện tại và bật dự án để chatbot sử dụng. Tiếp tục?",
    );
    expect(mocks.replaceProjectSinglePage).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("shows current category data without the category template download action", async () => {
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

    await screen.getByRole("button", { name: "Vị trí tuyển dụng" }).click();
    const jobsEditor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
    );
    await expect.element(jobsEditor).toHaveValue("CURRENT JOBS");
    await expect.element(jobsEditor).toHaveAttribute("readonly");
    await expect.element(jobsEditor).toBeVisible();
    expect(
      Array.from(screen.container.querySelectorAll("button")).some(
        (button) => button.textContent?.trim() === "Tải mẫu",
      ),
    ).toBe(false);
    await expect
      .element(screen.getByRole("button", { name: "Sửa nội dung" }))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain(
      "Kiểm tra và thay thế mục này",
    );
    expect(screen.container.textContent).not.toContain("Xóa dữ liệu mục");
    await expect.element(screen.getByText("Nhập từ tệp văn bản")).toBeVisible();
    await expect
      .element(
        screen.getByText(
          "Dữ liệu hiện tại chatbot đang sử dụng · jobs-current.yaml",
        ),
      )
      .toBeVisible();

    await screen.getByRole("button", { name: "Lương & thu nhập" }).click();

    expect(
      screen.container.querySelector(
        '[aria-label="Dữ liệu hiện tại của danh mục Lương & thu nhập"]',
      ),
    ).toBeNull();
    expect(screen.container.textContent).not.toContain("TEMPLATE compensation");
    expect(
      Array.from(screen.container.querySelectorAll("button")).some(
        (button) => button.textContent?.trim() === "Tải mẫu",
      ),
    ).toBe(false);
    await expect
      .element(
        screen.getByText(
          "Danh mục này chưa có dữ liệu đang dùng. Nhập tệp văn bản của dự án để hệ thống phân loại nội dung.",
        ),
      )
      .toBeVisible();
    expect(
      screen.container.querySelector(
        '.project-category-editor-heading [data-slot="badge"]',
      )?.textContent,
    ).toBe("Chưa có dữ liệu");
    await screen.getByRole("button", { name: "Sửa nội dung" }).click();
    await expect
      .element(
        screen.getByLabelText("Dữ liệu hiện tại của danh mục Lương & thu nhập"),
      )
      .toHaveValue("TEMPLATE compensation");
  });

  it("decodes raw newline escapes in the readonly category view", async () => {
    // FE-31: KB source escapes rendered as literal \n text in the readonly
    // markdown textarea, which read as a rendering bug to operators.
    mocks.getProjectKnowledgeCategorySource.mockImplementation(
      (_projectId: string, key: string) => {
        if (key === "jobs") {
          return Promise.resolve({
            key,
            label_vi: "Vị trí tuyển dụng",
            revision_id: "revision-jobs",
            revision_no: 2,
            filename: "jobs-current.yaml",
            content: 'summary: "Dòng một.\\nDòng hai."',
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

    await screen.getByRole("button", { name: "Vị trí tuyển dụng" }).click();
    const jobsEditor = screen.getByLabelText(
      "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
    );
    await expect
      .element(jobsEditor)
      .toHaveValue('summary: "Dòng một.\nDòng hai."');
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
    // Upload acceptance is not publication: keep showing the currently active
    // source while the proposed replacement is being reviewed.
    await expect.element(editor).toHaveValue("jobs:\n  - id: old");
    await expect
      .element(screen.getByRole("button", { name: "Sửa nội dung" }))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("Tải file YAML");
    expect(screen.container.textContent).not.toContain("Sync From Link");
  });

  it("offers source-read recovery without enabling a blank replacement", async () => {
    mocks.getProjectKnowledgeCategorySource.mockRejectedValue(
      new ApiError(503, "Chưa đọc được nguồn hiện tại"),
    );
    const screen = await renderPanel(
      <ProjectKnowledgePanel
        project={project}
        editable
        canManageSources={false}
      />,
    );
    await expect.element(screen.getByRole("alert")).toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Sửa nội dung" }))
      .toBeDisabled();
    expect(
      screen.container.querySelector(".project-category-editor-heading")
        ?.textContent,
    ).not.toContain("Chưa có dữ liệu");
    mocks.getProjectKnowledgeCategorySource.mockResolvedValue({
      key: "jobs",
      label_vi: "Vị trí tuyển dụng",
      revision_id: "revision-jobs",
      revision_no: 2,
      filename: "jobs-current.yaml",
      content: "CURRENT JOBS",
      checksum: "checksum",
      updated_at: "2026-10-01T00:00:00Z",
    });
    await screen.getByRole("button", { name: "Thử lại", exact: true }).click();
    await expect
      .element(
        screen.getByLabelText(
          "Dữ liệu hiện tại của danh mục Vị trí tuyển dụng",
        ),
      )
      .toHaveValue("CURRENT JOBS");
    await expect
      .element(screen.getByRole("button", { name: "Sửa nội dung" }))
      .toBeEnabled();
    expect(mocks.replaceProjectKnowledgeCategory).not.toHaveBeenCalled();
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
    // The selected category's YAML must be visible with no second interaction.
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
    // The phone picker is a Untitled UI `Select`; the console class is what
    // shows and hides it, so this asserts the control it wraps is on screen.
    const mobileSelector = screen.container.querySelector(
      ".project-category-mobile-select",
    );
    const detail = screen.container.querySelector("#project-category-detail");
    expect(workspace).toBeInstanceOf(HTMLElement);
    expect(navigation).toBeInstanceOf(HTMLElement);
    expect(detail).toBeInstanceOf(HTMLElement);
    expect(mobileSelector).toBeInstanceOf(HTMLElement);

    const workspaceStyle = window.getComputedStyle(workspace as HTMLElement);
    const navigationBounds = (
      navigation as HTMLElement
    ).getBoundingClientRect();
    const detailBounds = (detail as HTMLElement).getBoundingClientRect();
    expect(window.getComputedStyle(mobileSelector as HTMLElement).display).toBe(
      "block",
    );
    expect(
      (mobileSelector as HTMLElement).getBoundingClientRect().height,
    ).toBeGreaterThan(0);
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

  it("ingests a markdown brief through the revision pipeline, jobs first", async () => {
    mocks.getProjectKnowledgeCategorySource.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    mocks.replaceProjectKnowledgeCategory.mockImplementation(
      async (_projectId: string, key: string) => ({
        revision: { id: `rev-${key}` },
      }),
    );
    // The ingest chain must await real activation: every catalog poll reports
    // each written revision as ACTIVE, so nothing stalls.
    mocks.getProjectKnowledgeCategories.mockImplementation(async () => {
      const rows = (
        [
          "jobs",
          "compensation",
          "requirements",
          "work_schedules",
          "benefits",
          "accommodation",
          "meals",
          "transportation",
          "insurance",
          "application",
          "contacts",
          "faq",
        ] as const
      ).map((key) => ({
        key,
        label_vi: key,
        active_revision_id: `rev-${key}`,
        latest_revision_id: `rev-${key}`,
        status: "ACTIVE",
      }));
      return { data: rows, total: rows.length };
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the panel renders no brief input");
    const file = new File([amtranBrief], "phieu-amtran.md", {
      type: "text/markdown",
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));

    await vi.waitFor(() =>
      expect(mocks.uploadProjectDocument).toHaveBeenCalled(),
    );

    // The source explicitly has no shuttle service. It must not create a
    // fictional route just to complete the category count.
    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 11 phần kiến thức/))
          .toBeVisible(),
      { timeout: 60000 },
    );

    const keys = plannedWrites().map((write) => write.key);
    // Categories are written in catalog order and scoped to the project.
    expect(keys[0]).toBe("jobs");
    // The content-driven rule: every category this sheet genuinely carries is
    // written, jobs first and the rest in catalog order.
    expect(keys).toEqual([
      "jobs",
      "compensation",
      "requirements",
      "work_schedules",
      "benefits",
      "accommodation",
      "meals",
      "insurance",
      "application",
      "contacts",
      "faq",
    ]);
    const jobsMarkdown = plannedWrites()[0].content;
    expect(jobsMarkdown).toContain("Nhân viên lắp ráp linh kiện điện tử");
    expect(jobsMarkdown).not.toMatch(
      /^\s*(?:jobs?_ids|vacancies|employment_type)\s*:/m,
    );

    expect(screen.container.textContent).toContain(
      "Cần nhập tay: Đưa đón & lịch xe",
    );
    // Replacements are revisioned (the superseded revision stays archived),
    // so the writes proceed without asking anyone first.
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  }, 60000);

  it("parses a plain-text (.txt) brief and writes it without prompting", async () => {
    mocks.replaceProjectKnowledgeCategory.mockImplementation(
      async (_projectId: string, key: string) => ({
        revision: { id: `rev-${key}` },
      }),
    );
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the panel renders no brief input");
    const file = new File([REUPLOAD_BRIEF], "phieu-4p.txt", {
      type: "text/plain",
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));

    // The .txt pick passed the text-file guard and went through
    // parseProjectBrief + planBriefKnowledge straight into the chain: the
    // writes proceed with nobody asked to confirm a replacement.
    await vi.waitFor(
      () =>
        expect(screen.getByText(/Đã nạp xong 3 phần kiến thức/)).toBeVisible(),
      { timeout: 30000 },
    );
    const { key: firstKey, filename: firstFilename } = plannedWrites()[0];
    expect(firstKey).toBe("jobs");
    expect(firstFilename).toBe("jobs.md");
    expect(screen.container.textContent).not.toContain("Chỉ chấp nhận tệp");
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  }, 30000);

  it("rejects a non-text file with the text-file message, before any read", async () => {
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the panel renders no brief input");
    const file = new File(["binary payload"], "phieu-brief.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));

    await expect
      .element(screen.getByText("Chỉ chấp nhận tệp văn bản."))
      .toBeVisible();
    // The guard fires before any read: no parse, no chain, no document upload.
    expect(mocks.replaceProjectKnowledgeCategory).not.toHaveBeenCalled();
    expect(mocks.uploadProjectDocument).not.toHaveBeenCalled();
  });

  it("re-ingest on a project with active categories rewrites every category, unprompted", async () => {
    // The categories the new file covers already carry active revisions —
    // existing content must neither gate the writes nor trigger a prompt.
    mocks.getProjectKnowledgeCategories.mockResolvedValue({
      data: ["jobs", "compensation", "faq"].map((key) => ({
        key,
        label_vi: key,
        active_revision_id: `old-${key}`,
        active_revision_no: 2,
        latest_revision_id: `old-${key}`,
        status: "ACTIVE",
      })),
      total: 3,
    });
    mocks.replaceProjectKnowledgeCategory.mockImplementation(
      async (_projectId: string, key: string) => ({
        revision: { id: `rev-${key}` },
      }),
    );
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the panel renders no brief input");
    const file = new File([REUPLOAD_BRIEF], "phieu-4p-cap-nhat.md", {
      type: "text/markdown",
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));

    await vi.waitFor(
      () =>
        expect(screen.getByText(/Đã nạp xong 3 phần kiến thức/)).toBeVisible(),
      { timeout: 30000 },
    );
    // The full set the file derives, jobs first — no category is skipped for
    // already having content…
    expect(plannedWrites().map((write) => write.key)).toEqual([
      "jobs",
      "compensation",
      "faq",
    ]);
    // …and nobody was asked to confirm the replacement.
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  }, 30000);

  it("uploads the picked brief as a project document alongside the writes", async () => {
    mocks.replaceProjectKnowledgeCategory.mockImplementation(
      async (_projectId: string, key: string) => ({
        revision: { id: `rev-${key}` },
      }),
    );

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the panel renders no brief input");
    const file = new File([REUPLOAD_BRIEF], "phieu-4p.md", {
      type: "text/markdown",
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));

    await vi.waitFor(() =>
      expect(mocks.uploadProjectDocument).toHaveBeenCalledTimes(1),
    );
    const [projectId, uploaded] = mocks.uploadProjectDocument.mock.calls[0];
    expect(projectId).toBe("project-1");
    expect((uploaded as File).name).toBe("phieu-4p.md");
    // The upload rides alongside the category writes, never in their place.
    await vi.waitFor(
      () =>
        expect(screen.getByText(/Đã nạp xong 3 phần kiến thức/)).toBeVisible(),
      { timeout: 30000 },
    );
    expect(plannedWrites().map((write) => write.key)).toEqual([
      "jobs",
      "compensation",
      "faq",
    ]);
  }, 30000);

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

  it("does not publish new highlights when a source update fails", async () => {
    mocks.uploadProjectDocument.mockRejectedValue(
      new Error("Máy chủ từ chối tệp."),
    );
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );
    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]')!;
    dropBrief(input, REUPLOAD_BRIEF, "phieu-that-bai.txt");
    await expect.element(screen.getByText(/Máy chủ từ chối tệp/)).toBeVisible();
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
  });

  it("leaves full-source discovery claims to the worker after a re-ingest", async () => {
    // Each written revision is accepted immediately (the catalog tracks older
    // revisions), so the chain completes without stalls.
    mocks.getProjectKnowledgeCategories.mockResolvedValue({
      data: ["jobs", "compensation", "faq"].map((key) => ({
        key,
        label_vi: key,
        active_revision_id: `old-${key}`,
        latest_revision_id: `old-${key}`,
        status: "ACTIVE",
      })),
      total: 3,
    });
    mocks.replaceProjectKnowledgeCategory.mockImplementation(
      async (_projectId: string, key: string) => ({
        revision: { id: `rev-${key}` },
      }),
    );

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the panel renders no brief input");
    const file = new File([REUPLOAD_BRIEF], "phieu-4p.md", {
      type: "text/markdown",
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));

    await expect
      .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
      .toBeVisible();
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
    // Source-derived discovery claims belong to the backend's full-source pass.
    expect(plannedWrites().map((write) => write.key)).toEqual([
      "jobs",
      "compensation",
      "faq",
    ]);
    await vi.waitFor(() =>
      expect(
        mocks.getProjectKnowledgeCategories.mock.calls.length,
      ).toBeGreaterThan(1),
    );
  }, 30000);

  it("sends no discovery-card patch when the re-ingested brief carries no highlights", async () => {
    mocks.getProjectKnowledgeCategories.mockResolvedValue({
      data: ["jobs", "compensation", "faq"].map((key) => ({
        key,
        label_vi: key,
        active_revision_id: `old-${key}`,
        latest_revision_id: `old-${key}`,
        status: "ACTIVE",
      })),
      total: 3,
    });
    mocks.replaceProjectKnowledgeCategory.mockImplementation(
      async (_projectId: string, key: string) => ({
        revision: { id: `rev-${key}` },
      }),
    );

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );

    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("the panel renders no brief input");
    const file = new File([NO_HIGHLIGHTS_BRIEF], "phieu-4p-khac.md", {
      type: "text/markdown",
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));

    await vi.waitFor(
      () =>
        expect(screen.getByText(/Đã nạp xong 3 phần kiến thức/)).toBeVisible(),
      { timeout: 30000 },
    );
    // No highlight facts, no patch — the card keeps its derived empty list.
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
  }, 30000);

  /** The migration affordance lives in its own section; its brief input is
   *  the one that carries the single-page → catalog cutover. */
  const migrationInput = (screen: { container: HTMLElement }) => {
    const input = screen.container.querySelector<HTMLInputElement>(
      '.project-migration-section input[type="file"]',
    );
    if (!input) throw new Error("the migration section renders no brief input");
    return input;
  };

  const dropBrief = (input: HTMLInputElement, brief: string, name: string) => {
    const file = new File([brief], name, { type: "text/markdown" });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };

  it("offers migration for single-page and legacy RAG projects, but not active catalogs", async () => {
    mocks.getProjectSinglePage.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    await expect
      .element(screen.getByText("Chuyển sang kiến thức 12 danh mục"))
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("button", {
          name: "Nhập tệp và chuyển đổi",
        }),
      )
      .toBeVisible();

    const ragScreen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );
    expect(
      ragScreen.container.querySelector(".project-migration-section"),
    ).toBeNull();
    expect(ragScreen.container.textContent).not.toContain(
      "Chuyển sang 12 danh mục",
    );

    const legacyScreen = await renderPanel(
      <ProjectKnowledgePanel
        project={{ ...project, category_authority_started: false }}
        editable
      />,
    );
    await expect
      .element(
        legacyScreen.container.querySelector<HTMLElement>(
          ".project-migration-section",
        ),
      )
      .toBeVisible();
  });

  it("migrates legacy RAG without clearing retained active or explicitly empty categories", async () => {
    mocks.getProjectKnowledgeCategories.mockResolvedValue({
      data: [
        ...categories,
        {
          key: "requirements",
          label_vi: "Yêu cầu",
          active_revision_id: "retained-requirements",
          status: "ACTIVE",
        },
        { key: "benefits", label_vi: "Phúc lợi", status: "CLEARED" },
      ],
      total: 4,
    });
    mocks.getProjectTrainingDocument.mockImplementation(async () => ({
      id: "training-document",
      status: "PUBLISHED",
      stage: "COMPLETED",
      error: null,
      project_training: {
        status: "COMPLETED",
        current: null,
        completed: plannedWrites().map((write) => write.key),
        error: null,
        requires_cutover: true,
      },
    }));
    const screen = await renderPanel(
      <ProjectKnowledgePanel
        project={{ ...project, category_authority_started: false }}
        editable
      />,
    );
    dropBrief(migrationInput(screen), REUPLOAD_BRIEF, "legacy-project.md");
    await vi.waitFor(
      () =>
        expect(mocks.cutoverProjectKnowledgeCategories).toHaveBeenCalledTimes(
          1,
        ),
      { timeout: 30000 },
    );
    const cleared = mocks.clearProjectKnowledgeCategory.mock.calls.map(
      (call) => call[1],
    );
    expect(cleared).not.toContain("requirements");
    expect(cleared).not.toContain("benefits");
    expect(cleared).not.toContain("faq");
    expect(cleared).toContain("contacts");
    expect(
      mocks.clearProjectKnowledgeCategory.mock.calls.every(
        (call) => call[2] === 0,
      ),
    ).toBe(true);
    expect(mocks.refresh).toHaveBeenCalled();
  }, 30000);

  it("stops migration if another administrator writes a previously empty category", async () => {
    mocks.clearProjectKnowledgeCategory.mockRejectedValue(
      new ApiError(
        409,
        "Danh mục đã được cập nhật. Hãy làm mới trước khi thử lại.",
      ),
    );
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    dropBrief(migrationInput(screen), REUPLOAD_BRIEF, "guarded-migration.md");
    await expect
      .element(screen.getByText(/chưa chuyển được sang 12 danh mục/))
      .toBeVisible();
    expect(mocks.clearProjectKnowledgeCategory).toHaveBeenCalledWith(
      "project-rorze",
      "requirements",
      0,
    );
    expect(mocks.cutoverProjectKnowledgeCategories).not.toHaveBeenCalled();
    expect(mocks.refresh).not.toHaveBeenCalled();
  }, 30000);

  it("leaves an existing unpublished category revision for review instead of clearing it", async () => {
    mocks.getProjectKnowledgeCategories.mockResolvedValue({
      data: [
        ...categories,
        {
          key: "requirements",
          label_vi: "Yêu cầu",
          latest_revision_id: "unpublished",
          latest_revision_no: 3,
          status: "FAILED",
        },
      ],
      total: 3,
    });
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    dropBrief(migrationInput(screen), REUPLOAD_BRIEF, "retained-revision.md");
    await expect
      .element(screen.getByText(/đã có phiên bản chưa được kích hoạt/))
      .toBeVisible();
    expect(mocks.clearProjectKnowledgeCategory).not.toHaveBeenCalled();
    expect(mocks.cutoverProjectKnowledgeCategories).not.toHaveBeenCalled();
  }, 30000);

  it("reports the current category ordinal even before the atomic activation receipt", async () => {
    mocks.getProjectTrainingDocument.mockResolvedValue({
      id: "training-document",
      status: "PROCESSING",
      error: null,
      project_training: {
        status: "PROCESSING",
        current: "benefits",
        completed: [],
        planned: PROJECT_KNOWLEDGE_CATEGORIES,
        error: null,
      },
    });
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );
    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]')!;
    dropBrief(input, REUPLOAD_BRIEF, "all-categories.md");
    await expect
      .element(screen.getByText("Đang nạp «Phúc lợi» (5/12)…"))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("(1/12)");
    expect(mocks.cutoverProjectKnowledgeCategories).not.toHaveBeenCalled();
  }, 30000);

  it("cuts a migrated single-page project over exactly once after the chain lands", async () => {
    mocks.getProjectSinglePage.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    mocks.replaceProjectKnowledgeCategory.mockImplementation(
      async (_projectId: string, key: string) => ({
        revision: { id: `rev-${key}` },
      }),
    );
    // The ingest chain must await real activation: every catalog poll reports
    // each written revision as ACTIVE, so nothing stalls.
    mocks.getProjectKnowledgeCategories.mockImplementation(async () => {
      const rows = (
        [
          "jobs",
          "compensation",
          "requirements",
          "work_schedules",
          "benefits",
          "accommodation",
          "meals",
          "transportation",
          "insurance",
          "application",
          "contacts",
          "faq",
        ] as const
      ).map((key) => ({
        key,
        label_vi: key,
        active_revision_id: `rev-${key}`,
        latest_revision_id: `rev-${key}`,
        status: "ACTIVE",
      }));
      return { data: rows, total: rows.length };
    });

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    dropBrief(
      migrationInput(screen),
      REUPLOAD_BRIEF,
      "phieu-rorze-chuyen-doi.md",
    );

    await vi.waitFor(
      () =>
        expect(mocks.cutoverProjectKnowledgeCategories).toHaveBeenCalledTimes(
          1,
        ),
      { timeout: 30000 },
    );
    expect(mocks.cutoverProjectKnowledgeCategories).toHaveBeenCalledWith(
      "project-rorze",
    );
    // The catalog already has all categories active. Missing brief sections
    // retain those revisions rather than clearing existing knowledge.
    expect(
      mocks.clearProjectKnowledgeCategory.mock.calls.map((call) => call[1]),
    ).toEqual([]);
    // Every clear precedes the one and only cutover call.
    const cutoverOrder =
      mocks.cutoverProjectKnowledgeCategories.mock.invocationCallOrder[0];
    const lastClearOrder =
      mocks.clearProjectKnowledgeCategory.mock.invocationCallOrder.at(-1) ?? 0;
    expect(lastClearOrder).toBeLessThan(cutoverOrder);
    // The record re-read makes the panel come back as the category catalog.
    expect(mocks.refresh).toHaveBeenCalled();
    expect(mocks.notify).toHaveBeenCalledWith(
      "Dự án đã chuyển sang kiến thức 12 danh mục.",
      { type: "success" },
    );
  }, 30000);

  it("leaves the single page untouched when the chain fails before the cutover", async () => {
    mocks.getProjectSinglePage.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    mocks.uploadProjectDocument.mockRejectedValue(
      new ApiError(500, "hệ thống quá tải"),
    );

    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    dropBrief(
      migrationInput(screen),
      REUPLOAD_BRIEF,
      "phieu-rorze-that-bai.md",
    );

    await expect
      .element(screen.getByText(/Chưa nạp được tệp: hệ thống quá tải/))
      .toBeVisible();
    // No clears, no cutover: nothing moved while the chain never landed.
    expect(mocks.clearProjectKnowledgeCategory).not.toHaveBeenCalled();
    expect(mocks.cutoverProjectKnowledgeCategories).not.toHaveBeenCalled();
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
  }, 30000);

  it("reports shadow preparation and keeps source claims private when explicit cutover fails", async () => {
    mocks.getProjectSinglePage.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    mocks.getProjectTrainingDocument.mockImplementation(async () => ({
      id: "document-1",
      status: "PUBLISHED",
      stage: "COMPLETED",
      error: null,
      project_training: {
        status: "COMPLETED",
        current: null,
        completed: plannedWrites().map((write) => write.key),
        error: null,
        requires_cutover: true,
      },
    }));
    const cutover = deferred<never>();
    mocks.cutoverProjectKnowledgeCategories.mockReturnValue(cutover.promise);
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    dropBrief(migrationInput(screen), REUPLOAD_BRIEF, "phieu-chua-chuyen.md");
    await vi.waitFor(
      () =>
        expect(mocks.cutoverProjectKnowledgeCategories).toHaveBeenCalledTimes(
          1,
        ),
      { timeout: 30000 },
    );
    await expect
      .element(screen.getByText(/Đã chuẩn bị và kiểm tra 3 phần kiến thức/))
      .toBeVisible();
    await expect
      .element(screen.getByText(/Nguồn kiến thức hiện tại vẫn được dùng/))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("Đã nạp xong");
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
    cutover.reject(new Error("Cần xác nhận danh mục"));
    await expect
      .element(screen.getByText(/chưa chuyển được sang 12 danh mục/))
      .toBeVisible();
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(mocks.notify).not.toHaveBeenCalledWith(
      "Dự án đã chuyển sang kiến thức 12 danh mục.",
      { type: "success" },
    );
  }, 30000);

  it("does not publish a shadow receipt's highlights from a stale RAG panel's catalog reload", async () => {
    mocks.getProjectTrainingDocument.mockImplementation(async () => ({
      id: "document-1",
      status: "PUBLISHED",
      stage: "COMPLETED",
      error: null,
      project_training: {
        status: "COMPLETED",
        current: null,
        completed: plannedWrites().map((write) => write.key),
        error: null,
        requires_cutover: true,
      },
    }));
    // The operator's loaded project is RAG, but the exact source receipt is
    // authoritative after another administrator has rolled its authority back.
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={project} editable />,
    );
    const input =
      screen.container.querySelector<HTMLInputElement>('input[type="file"]')!;
    dropBrief(input, REUPLOAD_BRIEF, "phieu-rag-cu.md");
    await expect
      .element(screen.getByText(/Đã chuẩn bị và kiểm tra 3 phần kiến thức/))
      .toBeVisible();
    await vi.waitFor(() =>
      expect(
        mocks.getProjectKnowledgeCategories.mock.calls.length,
      ).toBeGreaterThan(1),
    );
    expect(mocks.cutoverProjectKnowledgeCategories).not.toHaveBeenCalled();
    expect(mocks.clearProjectKnowledgeCategory).not.toHaveBeenCalled();
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
    expect(screen.container.textContent).not.toContain("Đã nạp xong");
  });

  it("does not replay shadow-source highlights after successful explicit cutover", async () => {
    mocks.getProjectSinglePage.mockRejectedValue(
      new ApiError(404, "Chưa có dữ liệu"),
    );
    mocks.getProjectTrainingDocument.mockImplementation(async () => ({
      id: "document-1",
      status: "PUBLISHED",
      stage: "COMPLETED",
      error: null,
      project_training: {
        status: "COMPLETED",
        current: null,
        completed: plannedWrites().map((write) => write.key),
        error: null,
        requires_cutover: true,
      },
    }));
    const screen = await renderPanel(
      <ProjectKnowledgePanel project={singlePageProject} editable />,
    );
    const input = migrationInput(screen);
    dropBrief(input, REUPLOAD_BRIEF, "phieu-cu-da-chuyen.md");
    // The input reset is the final step of this upload handler. Wait for it
    // rather than checking before a post-cutover claim write could execute.
    expect(input.value).not.toBe("");
    await vi.waitFor(() => expect(input.value).toBe(""), { timeout: 30000 });
    expect(mocks.cutoverProjectKnowledgeCategories).toHaveBeenCalledTimes(1);
    expect(mocks.notify).toHaveBeenCalledWith(
      "Dự án đã chuyển sang kiến thức 12 danh mục.",
      { type: "success" },
    );
    expect(mocks.refresh).toHaveBeenCalled();
    // The backend may adopt these claims or keep independent newer features.
    // Frontend replay would undo that atomic ownership decision in either case.
    expect(mocks.updateProjectDiscoveryCard).not.toHaveBeenCalled();
  }, 30000);
});
