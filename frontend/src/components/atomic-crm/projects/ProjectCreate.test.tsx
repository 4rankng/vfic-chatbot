import type { ReactNode } from "react";
import type * as KnowledgeServiceModule from "./project-knowledge-service";
import { render, type RenderResult } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The `await import("react-hook-form")` inside the vi.mock factory is the one
// case a static import cannot serve: a mock factory runs through the module
// registry, so the real module has to be fetched at factory time.
const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  notify: vi.fn(),
  replaceCategory: vi.fn(),
  /** Swapped per test to decide what the pipeline reports back. */
  catalog: vi.fn(),
  /** The brief-document upload: resolves unless a test rejects it. */
  uploadDoc: vi.fn(),
  trainingDoc: vi.fn(),
  /** The brief's highlights PATCHed onto the discovery card. */
  updateCard: vi.fn(),
}));

/** Vitest's browser render result, named by the library rather than inferred
 *  from the call — the helper must not couple to `render`'s implementation. */
type CreateForm = RenderResult;

vi.mock("ra-core", async () => {
  // react-admin's `Form` is a react-hook-form `FormProvider`. A plain <form>
  // stub would throw here and hide the wiring the form depends on.
  const { FormProvider, useForm } = await import("react-hook-form");

  return {
    CreateBase: ({ children }: { children: ReactNode }) => <>{children}</>,
    Form: ({
      children,
      onSubmit,
    }: {
      children: ReactNode;
      onSubmit: () => void;
    }) => {
      const form = useForm();
      return (
        <FormProvider {...form}>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              onSubmit();
            }}
          >
            {children}
          </form>
        </FormProvider>
      );
    },
    useDataProvider: () => ({ create: mocks.create, update: mocks.update }),
    useNotify: () => mocks.notify,
    useRedirect: () => mocks.redirect,
  };
});

vi.mock("./project-knowledge-service", async (importOriginal) => ({
  ...(await importOriginal<typeof KnowledgeServiceModule>()),
  replaceProjectKnowledgeCategory: mocks.replaceCategory,
  getProjectKnowledgeCategories: mocks.catalog,
  uploadProjectDocument: mocks.uploadDoc,
  getProjectTrainingDocument: mocks.trainingDoc,
  updateProjectDiscoveryCard: mocks.updateCard,
}));

vi.mock("./ProjectWorkspaceShell", () => ({
  ProjectWorkspaceShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));

import { ProjectCreate } from "./ProjectCreate";
import { parseProjectBrief } from "./domain/project-brief-ingest";
import { planBriefKnowledge } from "./domain/project-knowledge-markdown";

/** Provider receipt fixture; browser previews are never submitted as plans. */
let backendWrites: ReturnType<typeof planBriefKnowledge>["writes"] = [];

/** The shape of a real brief: an overview table plus Q&A sections. */
const BRIEF = `# PHIẾU THU THẬP
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

/** The same brief with its highlights row removed: a file carrying no
 *  "Các điểm nổi bật" facts must send no discovery-card patch at all. */
const NO_HIGHLIGHTS_BRIEF = BRIEF.replace(/^.*Các điểm nổi bật.*\n/gm, "");

/**
 * Hand the component a real File through the hidden input, the way a pick does:
 * the input's `files` list plus a bubbling `change`. The component reads it via
 * `File.text()`, so the payload is a genuine File, not a stubbed handler.
 * `filename`/`type` let a test pick the file shape under test.
 */
const uploadBrief = (
  screen: CreateForm,
  text: string = BRIEF,
  filename: string = "phiếu 4P.md",
  type: string = "text/markdown",
) => {
  const input =
    screen.container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("the brief import renders no file input");
  const file = new File([text], filename, { type });
  // A real `FileList` — `input.files` rejects a plain array.
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
};

/** A catalog row that has accepted the revision it is asked about. */
const plannedWrites = () => backendWrites;

const catalogWith = (
  revisionId: string,
  status: "ACTIVE" | "FAILED" = "ACTIVE",
) => ({
  data: [
    {
      key: "jobs",
      label_vi: "Vị trí tuyển dụng",
      active_revision_id: status === "ACTIVE" ? revisionId : null,
      latest_revision_id: revisionId,
      status,
      error_message:
        status === "FAILED" ? "Nội dung không truy xuất được." : null,
    },
    {
      key: "faq",
      label_vi: "Câu hỏi thường gặp",
      active_revision_id: null,
      latest_revision_id: null,
      status: null,
      error_message: null,
    },
  ],
  total: 2,
});

describe("ProjectCreate", () => {
  beforeEach(() => {
    mocks.redirect.mockReset();
    mocks.create.mockReset();
    mocks.update.mockReset();
    mocks.notify.mockReset();
    mocks.replaceCategory.mockReset();
    mocks.catalog.mockReset();
    mocks.uploadDoc.mockReset();
    mocks.updateCard.mockReset();
    mocks.trainingDoc.mockReset();
    backendWrites = [];
    mocks.uploadDoc.mockImplementation(async (_id: string, file: File) => {
      backendWrites = planBriefKnowledge(
        parseProjectBrief(await file.text()),
      ).writes;
      return { id: "training-document" };
    });
    mocks.trainingDoc.mockImplementation(async () => ({
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
    mocks.create.mockResolvedValue({ data: { id: "7" } });
    mocks.update.mockResolvedValue({ data: { id: "7" } });
    mocks.replaceCategory.mockImplementation(async (_id, key) => ({
      revision: { id: `rev-${key}` },
    }));
    // Every write is accepted on the first poll, so the chain completes.
    mocks.catalog.mockImplementation(async () => catalogWith("rev-jobs"));
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

  it("asks for a name, a derived slug, aliases and roles — and no knowledge mode", async () => {
    const screen = await render(<ProjectCreate />);

    await expect.element(screen.getByLabelText(/^Tên dự án/)).toBeVisible();
    await expect.element(screen.getByLabelText(/^Mã dự án/)).toBeVisible();
    await expect.element(screen.getByLabelText(/^Tên gọi khác/)).toBeVisible();
    await expect
      .element(screen.getByLabelText(/^Vị trí tuyển dụng/))
      .toBeVisible();
    // The mode radio is gone: the ingest pipeline decides the shape.
    expect(screen.container.querySelector('input[type="radio"]')).toBeNull();
  });

  it("derives the slug from the name the recruiter typed", async () => {
    const screen = await render(<ProjectCreate />);

    await screen.getByLabelText(/^Tên dự án/).fill("LG Display Hải Phòng");

    await expect
      .element(screen.getByLabelText(/^Mã dự án/))
      .toHaveValue("lg-display-hai-phong");
  });

  it("keeps the persisted draft code when the project is renamed", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalled());
    await screen.getByLabelText(/^Tên dự án/).fill("Tên mới của dự án");
    await expect
      .element(screen.getByLabelText(/^Mã dự án/))
      .toHaveValue("4p-electronic");
  });

  it("accepts a salary-only update when the recruiter supplied the project name", async () => {
    const screen = await render(<ProjectCreate />);
    await screen.getByLabelText(/^Tên dự án/).fill("Dự án đã biết");
    uploadBrief(
      screen,
      "## Lương và thu nhập\nLương cơ bản: 6.200.000 đồng/tháng.\n",
    );
    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalledTimes(1));
    expect(plannedWrites().map((write) => write.key)).toEqual(["compensation"]);
  });

  // Every Untitled UI control on this page must sit in a `.uu-scope` subtree.
  // Without it the library's `bg-primary` resolves to the console's slate
  // action fill, so the secondary buttons painted dark secondary ink on slate
  // (3.4:1) and the primary submit lost its `text-white` to the workspace's
  // `color: inherit` reset (also 3.4:1).
  it("scopes every Untitled UI control on the page", async () => {
    const screen = await render(<ProjectCreate />);

    const controls = [
      screen.getByRole("button", { name: "Đóng và quay lại danh sách dự án" }),
      screen.getByRole("button", { name: "Nhập từ tệp" }),
      screen.getByRole("button", { name: "Tạo dự án" }),
    ];

    for (const control of controls) {
      await expect.element(control).toBeVisible();
      expect(control.element().closest(".uu-scope")).not.toBeNull();
    }
  });
});

describe("ProjectCreate — nạp ngay khi chọn tệp", () => {
  beforeEach(() => {
    mocks.redirect.mockReset();
    mocks.create.mockReset();
    mocks.update.mockReset();
    mocks.notify.mockReset();
    mocks.replaceCategory.mockReset();
    mocks.catalog.mockReset();
    mocks.uploadDoc.mockReset();
    mocks.updateCard.mockReset();
    mocks.trainingDoc.mockReset();
    backendWrites = [];
    mocks.uploadDoc.mockImplementation(async (_id: string, file: File) => {
      backendWrites = planBriefKnowledge(
        parseProjectBrief(await file.text()),
      ).writes;
      return { id: "training-document" };
    });
    mocks.trainingDoc.mockImplementation(async () => ({
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
    mocks.create.mockResolvedValue({ data: { id: "7" } });
    mocks.update.mockResolvedValue({ data: { id: "7" } });
    mocks.replaceCategory.mockImplementation(async (_id, key) => ({
      revision: { id: `rev-${key}` },
    }));
    mocks.catalog.mockImplementation(async () => catalogWith("rev-jobs"));
  });

  it("creates the inactive draft on upload and never sends a discovery card", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const payload = mocks.create.mock.calls[0][1].data;
    expect(payload).toMatchObject({
      name: "4P ELECTRONIC",
      slug: "4p-electronic",
      knowledge_mode: "RAG",
      is_active: false,
    });
    expect(payload).not.toHaveProperty("discovery_card");
  });

  it("writes roles in catalog order without retired metadata", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalledTimes(1));
    await vi.waitFor(
      () =>
        expect(plannedWrites().map((write) => write.key)).toEqual([
          "jobs",
          "compensation",
          "faq",
        ]),
      { timeout: 20000 },
    );

    const jobsWrite = plannedWrites()[0];
    expect(jobsWrite.filename).toBe("jobs.md");
    expect(jobsWrite.content).toContain("category: jobs");
    expect(mocks.replaceCategory).not.toHaveBeenCalled();
    expect(jobsWrite.content).not.toMatch(
      /^\s*(?:jobs?_ids|vacancies|employment_type)\s*:/m,
    );
  }, 20000);

  it("fills the fields from the brief and leaves the typed name alone", async () => {
    const screen = await render(<ProjectCreate />);
    await screen.getByLabelText(/^Tên dự án/).fill("Tên tôi tự gõ");
    uploadBrief(screen);

    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][1].data.name).toBe("Tên tôi tự gõ");
    await expect
      .element(screen.getByLabelText(/^Tên gọi khác/))
      .toHaveValue("4P Electronics, 4P Hải Phòng");
  }, 20000);

  it("keeps Tạo dự án disabled until the pipeline has really finished", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    // Mid-pipeline the button must not be offered: activating here would
    // publish a project whose knowledge is still in review.
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeDisabled();

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
          .toBeVisible(),
      { timeout: 20000 },
    );
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeEnabled();
  }, 20000);

  it("activates the draft only when the admin presses Tạo dự án", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
          .toBeVisible(),
      { timeout: 20000 },
    );
    expect(mocks.update).not.toHaveBeenCalled();

    await screen.getByRole("button", { name: /Tạo dự án/ }).click();

    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.update.mock.calls[0][0]).toBe("projects");
    expect(mocks.update.mock.calls[0][1]).toMatchObject({
      id: "7",
      data: { name: "4P ELECTRONIC", is_active: true },
    });
  }, 20000);

  it("needs only the name, the file and one submit click — nothing else", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const screen = await render(<ProjectCreate />);

    // Exactly the admin's required input: a name and a file. No other field
    // is touched and no control is chosen.
    await screen.getByLabelText(/^Tên dự án/).fill("LG Display Hải Phòng");
    uploadBrief(screen);

    // The app does the rest: one draft, every category the file carries
    // (jobs first), and the brief file itself onto the document shelf.
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    await vi.waitFor(
      () =>
        expect(plannedWrites().map((write) => write.key)).toEqual([
          "jobs",
          "compensation",
          "faq",
        ]),
      { timeout: 20000 },
    );
    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalledTimes(1), {
      timeout: 10000,
    });
    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
          .toBeVisible(),
      { timeout: 20000 },
    );

    // One click is the single confirmation point.
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();
    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.update.mock.calls[0][1]).toMatchObject({
      id: "7",
      data: { name: "LG Display Hải Phòng", is_active: true },
    });
    expect(mocks.redirect).toHaveBeenCalledWith("show", "projects", "7");
    // Nothing along the way asked for permission.
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  }, 25000);

  it("re-picked file updates the same draft and re-runs the whole chain", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
          .toBeVisible(),
      { timeout: 20000 },
    );

    // The updated file arrives before the single create click.
    uploadBrief(screen);
    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalledTimes(2), {
      timeout: 20000,
    });

    // One project, knowledge updated in place — the second pick never
    // stranded a second draft — and both files reached the document shelf.
    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.uploadDoc).toHaveBeenCalledTimes(2);
  }, 30000);

  it("re-writes the jobs category when the admin edits the role list", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
          .toBeVisible(),
      { timeout: 20000 },
    );

    await screen
      .getByLabelText(/^Vị trí tuyển dụng/)
      .fill("Kiểm tra chất lượng");
    await expect
      .element(screen.getByText(/Danh sách vị trí đã sửa/))
      .toBeVisible();

    const initialLocation =
      plannedWrites()[0].content.match(/location: (.+)/)?.[0];
    expect(initialLocation).toBe('location: "Hải Phòng"');

    mocks.replaceCategory.mockClear();
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();

    await vi.waitFor(() =>
      expect(mocks.replaceCategory).toHaveBeenCalledTimes(1),
    );
    const [, key, , content] = mocks.replaceCategory.mock.calls[0];
    expect(key).toBe("jobs");
    expect(content).toContain('title: "Kiểm tra chất lượng"');
    expect(content).toContain(initialLocation!);
  }, 25000);

  it("keeps the draft inactive and shows the reason when a write fails", async () => {
    mocks.trainingDoc.mockResolvedValue({
      status: "FAILED",
      error: "Nội dung không truy xuất được.",
      project_training: {
        status: "FAILED",
        current: "jobs",
        completed: [],
        error: "Nội dung không truy xuất được.",
      },
    });
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByRole("alert"))
          .toHaveTextContent(/Chưa xác nhận hoàn tất «Vị trí tuyển dụng»/),
      { timeout: 10000 },
    );
    // The draft is never published on a failed worker run.
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeDisabled();
    expect(mocks.update).not.toHaveBeenCalled();
    await expect
      .element(screen.getByRole("button", { name: "Kiểm tra bản nháp" }))
      .toBeVisible();
  }, 20000);

  it("reports each pipeline checkpoint on the timeline while the chain runs", async () => {
    mocks.trainingDoc
      .mockResolvedValueOnce({
        id: "training-document",
        status: "PROCESSING",
        error: null,
        project_training: {
          status: "PROCESSING",
          current: "jobs",
          completed: ["requirements"],
          planned: ["requirements", "jobs"],
          error: null,
        },
      })
      .mockResolvedValue({
        id: "training-document",
        status: "PUBLISHED",
        error: null,
        project_training: {
          status: "COMPLETED",
          current: null,
          completed: ["requirements", "jobs"],
          error: null,
        },
      });
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    // Mid-chain: the category loop is on jobs, everything before it is done.
    await expect
      .element(screen.getByText("Đang nạp «Vị trí tuyển dụng» (2/2)…"))
      .toBeVisible();
    const timeline = screen.container.querySelector<HTMLOListElement>(
      'ol[aria-label="Tiến độ nạp kiến thức"]',
    );
    if (!timeline) throw new Error("the timeline is not rendered");
    expect(timeline.textContent).toContain("Đọc tệp");
    expect(timeline.textContent).toContain("Tạo bản nháp dự án");
    expect(timeline.textContent).toContain("Phân tích nội dung tệp");
    expect(timeline.textContent).toContain("Phân loại vào 12 danh mục");

    // The final poll confirms both categories; the timeline reports finish.
    await expect
      .element(screen.getByText("Đã nạp 2 danh mục kiến thức."))
      .toBeVisible();
  }, 30000);

  it("keeps a name-only file as a draft without claiming searchable knowledge", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen, "Tên dự án: Dự án trống\n");
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Hệ thống chưa xác nhận đầy đủ các danh mục");
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeDisabled();
    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.uploadDoc).toHaveBeenCalledTimes(1);
  });

  it("trains free-form text with no browser fields and activates without a fabricated roles write", async () => {
    mocks.trainingDoc.mockResolvedValue({
      id: "training-document",
      status: "PUBLISHED",
      error: null,
      project_training: {
        status: "COMPLETED",
        completed: ["jobs", "benefits", "transportation"],
        planned: ["jobs", "benefits", "transportation"],
        current: null,
        error: null,
      },
    });
    const screen = await render(<ProjectCreate />);
    uploadBrief(
      screen,
      "Công ty tuyển người đóng gói, thu nhập theo sản lượng, có xe đón từ bến xe.",
      "plain.log",
      "text/plain",
    );
    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalledTimes(1));
    expect(mocks.uploadDoc.mock.calls[0]).toHaveLength(2);
    expect(mocks.create.mock.calls[0][1].data.slug).toMatch(
      /^du-an-moi-[a-f0-9]{8}$/,
    );
    await screen.getByLabelText(/^Tên dự án/).fill("Dự án văn bản tự do");
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeEnabled();
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();
    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.replaceCategory).not.toHaveBeenCalled();
  });

  it("drops previous automatic roles and aliases when the next source has no preview fields", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeEnabled();
    mocks.trainingDoc.mockResolvedValue({
      id: "training-document",
      status: "PUBLISHED",
      error: null,
      project_training: {
        status: "COMPLETED",
        completed: ["jobs"],
        planned: ["jobs"],
        current: null,
        error: null,
      },
    });
    uploadBrief(
      screen,
      "Nhà máy đang cần người làm theo ca, mọi thông tin trong văn bản tự do.",
      "new.log",
    );
    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalledTimes(2));
    await expect
      .element(screen.getByLabelText(/^Vị trí tuyển dụng/))
      .toHaveValue("");
    await expect
      .element(screen.getByLabelText(/^Tên gọi khác/))
      .toHaveValue("");
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeEnabled();
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();
    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.replaceCategory).not.toHaveBeenCalled();
  });

  it("parses a plain-text (.txt) brief instead of demanding markdown", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(
      screen,
      "Tên dự án: Dự án văn bản thuần\n",
      "phieu-thong-tin.txt",
      "text/plain",
    );

    // Reaching the draft-create call with the parsed name proves the .txt
    // pick went through parseProjectBrief — no .md wall in the way.
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create.mock.calls[0][1].data.name).toBe("Dự án văn bản thuần");
  });

  it.each([
    ["bieu-mau.pdf", "application/pdf"],
    ["logo.png", "image/png"],
  ])(
    "rejects the non-text %s with the text-file message, before any read",
    async (filename, type) => {
      const screen = await render(<ProjectCreate />);
      uploadBrief(screen, "not a brief", filename, type);

      await expect
        .element(screen.getByRole("alert"))
        .toHaveTextContent(
          "Chỉ chấp nhận tệp văn bản (.txt, .md, .csv, .json…) hoặc tệp Word (.docx).",
        );
      expect(mocks.create).not.toHaveBeenCalled();
    },
  );

  it("hands a .docx pick to the backend instead of rejecting it client-side", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(
      screen,
      "not a brief",
      "phieu.docx",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    );

    // DOCX is a supported knowledge source: the guard no longer blocks it,
    // so the flow reaches the (mocked) backend chain and fails there on the
    // brief content, never with the text-file message.
    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create.mock.calls[0][1].data.name).toBeTruthy();
  });

  it("uploads the original brief file as a project knowledge document", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalledTimes(1), {
      timeout: 10000,
    });
    const [projectId, file] = mocks.uploadDoc.mock.calls[0];
    expect(projectId).toBe("7");
    expect((file as File).name).toBe("phiếu 4P.md");
    // The upload rides alongside the writes — never in their place.
    await vi.waitFor(
      () =>
        expect(plannedWrites().map((write) => write.key)).toEqual([
          "jobs",
          "compensation",
          "faq",
        ]),
      { timeout: 10000 },
    );
  }, 20000);

  it("keeps activation disabled when the durable upload fails", async () => {
    mocks.uploadDoc.mockRejectedValue(new Error("Máy chủ từ chối tệp."));
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Máy chủ từ chối tệp.");
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeDisabled();
    expect(mocks.replaceCategory).not.toHaveBeenCalled();
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("never uploads a document on a chain run without a source file", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
          .toBeVisible(),
      { timeout: 10000 },
    );
    // An edited role list makes the activation re-write the jobs category — a
    // chain run with no source file, the legacy caller shape — so it must
    // behave exactly as before: writes, no upload.
    await screen
      .getByLabelText(/^Vị trí tuyển dụng/)
      .fill("Kiểm tra chất lượng");
    mocks.uploadDoc.mockClear();
    mocks.replaceCategory.mockClear();
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();

    await vi.waitFor(() =>
      expect(mocks.replaceCategory).toHaveBeenCalledTimes(1),
    );
    expect(mocks.uploadDoc).not.toHaveBeenCalled();
  }, 25000);

  it("keeps preparation requiring authority cutover from enabling draft publication", async () => {
    mocks.trainingDoc.mockImplementation(async () => ({
      id: "training-document",
      status: "PUBLISHED",
      error: null,
      project_training: {
        status: "COMPLETED",
        current: null,
        completed: plannedWrites().map((write) => write.key),
        error: null,
        requires_cutover: true,
      },
    }));
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await expect
      .element(screen.getByText(/Đã chuẩn bị và kiểm tra 3 phần kiến thức/))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeDisabled();
    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.notify).not.toHaveBeenCalledWith(
      "Đã tạo dự án. Kiến thức đã sẵn sàng cho chatbot.",
      { type: "success" },
    );
    expect(mocks.updateCard).not.toHaveBeenCalled();
  });

  it("does not activate when the edited roles fail their revision review", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await expect
      .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
      .toBeVisible();
    await screen
      .getByLabelText(/^Vị trí tuyển dụng/)
      .fill("Kiểm tra chất lượng");
    mocks.catalog.mockResolvedValue(catalogWith("rev-jobs", "FAILED"));
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Nội dung không truy xuất được");
    expect(mocks.update).not.toHaveBeenCalled();
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeEnabled();
    mocks.catalog.mockResolvedValue(catalogWith("rev-jobs"));
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();
    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1), {
      timeout: 6000,
    });
    expect(mocks.uploadDoc).toHaveBeenCalledTimes(1);
  }, 15000);

  it("leaves source-derived discovery claims to the backend worker", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalled());
    expect(mocks.updateCard).not.toHaveBeenCalled();
    await expect
      .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
      .toBeVisible();
    expect(mocks.updateCard).not.toHaveBeenCalled();
    expect(mocks.trainingDoc).toHaveBeenCalled();
  }, 20000);

  it("sends no discovery-card patch when the brief carries no highlights", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen, NO_HIGHLIGHTS_BRIEF);

    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(mocks.uploadDoc).toHaveBeenCalled());
    // No highlight facts, no patch — the card keeps its derived empty list.
    expect(mocks.updateCard).not.toHaveBeenCalled();
  }, 20000);

  it("does not carry failed-source highlights into a later confirmed file", async () => {
    mocks.uploadDoc.mockRejectedValueOnce(new Error("Máy chủ từ chối tệp."));
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Máy chủ từ chối tệp.");
    expect(mocks.updateCard).not.toHaveBeenCalled();

    uploadBrief(screen, NO_HIGHLIGHTS_BRIEF, "phiếu-không-điểm-nổi-bật.md");
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeEnabled();
    expect(mocks.create).toHaveBeenCalledTimes(1);
    expect(mocks.uploadDoc).toHaveBeenCalledTimes(2);
    expect(mocks.updateCard).not.toHaveBeenCalled();
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();
    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
  }, 15000);
});
