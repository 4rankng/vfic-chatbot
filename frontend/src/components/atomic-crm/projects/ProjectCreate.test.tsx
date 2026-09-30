import type { ReactNode } from "react";
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

vi.mock("./project-knowledge-service", () => ({
  replaceProjectKnowledgeCategory: mocks.replaceCategory,
  getProjectKnowledgeCategories: mocks.catalog,
  uploadProjectDocument: mocks.uploadDoc,
  updateProjectDiscoveryCard: mocks.updateCard,
}));

vi.mock("./ProjectWorkspaceShell", () => ({
  ProjectWorkspaceShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));

import { ProjectCreate } from "./ProjectCreate";

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
    mocks.uploadDoc.mockResolvedValue(undefined);
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
    mocks.uploadDoc.mockResolvedValue(undefined);
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

  it("writes jobs first and never states a vacancy count", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(() =>
      expect(mocks.replaceCategory.mock.calls.length).toBeGreaterThan(0),
    );
    await vi.waitFor(
      () =>
        expect(mocks.replaceCategory.mock.calls.map((call) => call[1])).toEqual(
          ["jobs", "compensation", "faq"],
        ),
      { timeout: 20000 },
    );

    const jobsCall = mocks.replaceCategory.mock.calls[0];
    expect(jobsCall[0]).toBe("7");
    expect(jobsCall[2]).toBe("jobs.md");
    expect(jobsCall[3]).toContain("category: jobs");
    // The recruiter does not manage headcount, so the count renders as an explicit null.
    expect(jobsCall[3]).toContain("vacancies: null");
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
        expect(mocks.replaceCategory.mock.calls.map((call) => call[1])).toEqual(
          ["jobs", "compensation", "faq"],
        ),
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
    await vi.waitFor(
      () => expect(mocks.replaceCategory.mock.calls.length).toBe(6),
      { timeout: 20000 },
    );

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

    mocks.replaceCategory.mockClear();
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();

    await vi.waitFor(() =>
      expect(mocks.replaceCategory).toHaveBeenCalledTimes(1),
    );
    const [, key, , content] = mocks.replaceCategory.mock.calls[0];
    expect(key).toBe("jobs");
    expect(content).toContain('title: "Kiểm tra chất lượng"');
  }, 25000);

  it("keeps the draft inactive and shows the reason when a write fails", async () => {
    mocks.catalog.mockImplementation(async () =>
      catalogWith("rev-jobs", "FAILED"),
    );
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByRole("alert"))
          .toHaveTextContent(/Nạp «Vị trí tuyển dụng» không thành công/),
      { timeout: 10000 },
    );
    // The draft is never published on a failed write.
    expect(mocks.update).not.toHaveBeenCalled();
  }, 20000);

  it("demands nothing beyond the name and the file — roles stay optional", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen, "Tên dự án: Dự án trống\n");
    // No role entry and no other field: the single click must still create.

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByRole("button", { name: /Tạo dự án/ }))
          .toBeEnabled(),
      { timeout: 10000 },
    );
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();

    await vi.waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.update.mock.calls[0][1]).toMatchObject({
      id: "7",
      data: { is_active: true },
    });
    expect(mocks.notify).toHaveBeenCalledWith(
      "Đã tạo dự án. Kiến thức đã sẵn sàng cho Agent.",
      { type: "success" },
    );
    expect(mocks.notify).not.toHaveBeenCalledWith(
      expect.stringContaining("ít nhất một vị trí tuyển dụng"),
      expect.anything(),
    );
  }, 20000);

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
    [
      "phieu.docx",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ],
  ])(
    "rejects the non-text %s with the text-file message, before any read",
    async (filename, type) => {
      const screen = await render(<ProjectCreate />);
      uploadBrief(screen, "not a brief", filename, type);

      await expect
        .element(screen.getByRole("alert"))
        .toHaveTextContent("Chỉ chấp nhận tệp văn bản.");
      expect(mocks.create).not.toHaveBeenCalled();
    },
  );

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
        expect(mocks.replaceCategory.mock.calls.map((call) => call[1])).toEqual(
          ["jobs", "compensation", "faq"],
        ),
      { timeout: 10000 },
    );
  }, 20000);

  it("still completes the category writes when the document upload rejects", async () => {
    mocks.uploadDoc.mockRejectedValue(new Error("Máy chủ từ chối tệp."));
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    // Every category still lands…
    await vi.waitFor(
      () =>
        expect(mocks.replaceCategory.mock.calls.map((call) => call[1])).toEqual(
          ["jobs", "compensation", "faq"],
        ),
      { timeout: 10000 },
    );
    // …the chain still finishes…
    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 3 phần kiến thức/))
          .toBeVisible(),
      { timeout: 10000 },
    );
    // …the upload's own words surface as a non-fatal error…
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent(
        /Tệp phiếu chưa được lưu vào tài liệu dự án: Máy chủ từ chối tệp\./,
      );
    // …and the recruiter may still create the project.
    await expect
      .element(screen.getByRole("button", { name: /Tạo dự án/ }))
      .toBeEnabled();
  }, 20000);

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

  it("lands the brief's highlight facts on the discovery card before the writes", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(() => expect(mocks.updateCard).toHaveBeenCalledTimes(1));
    // Exactly the brief's facts, and nothing else, in the patch body.
    expect(mocks.updateCard.mock.calls[0]).toEqual([
      "7",
      {
        discovery_card: {
          highlights: ["Không yêu cầu bằng cấp.", "Đóng BHXH đầy đủ."],
        },
      },
    ]);
    // The PATCH rides before the category writes: activation preserves
    // `highlights`, so the facts are on the card before any projection runs.
    await vi.waitFor(() => expect(mocks.replaceCategory).toHaveBeenCalled());
    expect(mocks.updateCard.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.replaceCategory.mock.invocationCallOrder[0],
    );
  }, 20000);

  it("sends no discovery-card patch when the brief carries no highlights", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen, NO_HIGHLIGHTS_BRIEF);

    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(mocks.replaceCategory).toHaveBeenCalled());
    // No highlight facts, no patch — the card keeps its derived empty list.
    expect(mocks.updateCard).not.toHaveBeenCalled();
  }, 20000);
});
