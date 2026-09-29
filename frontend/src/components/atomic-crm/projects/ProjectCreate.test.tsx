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

/**
 * Hand the component a real File through the hidden input, the way a pick does:
 * the input's `files` list plus a bubbling `change`. The component reads it via
 * `File.text()`, so the payload is a genuine File, not a stubbed handler.
 */
const uploadBrief = (screen: CreateForm, text: string = BRIEF) => {
  const input =
    screen.container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("the brief import renders no file input");
  const file = new File([text], "phiếu 4P.md", { type: "text/markdown" });
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

    await expect.element(screen.getByLabelText("Tên dự án *")).toBeVisible();
    await expect.element(screen.getByLabelText("Mã dự án")).toBeVisible();
    await expect.element(screen.getByLabelText("Tên gọi khác")).toBeVisible();
    await expect
      .element(screen.getByLabelText("Vị trí tuyển dụng *"))
      .toBeVisible();
    // The mode radio is gone: the ingest pipeline decides the shape.
    expect(screen.container.querySelector('input[type="radio"]')).toBeNull();
  });

  it("derives the slug from the name the recruiter typed", async () => {
    const screen = await render(<ProjectCreate />);

    await screen.getByLabelText("Tên dự án *").fill("LG Display Hải Phòng");

    await expect
      .element(screen.getByLabelText("Mã dự án"))
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

  it("writes jobs before faq and never states a vacancy count", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(() =>
      expect(mocks.replaceCategory.mock.calls.length).toBeGreaterThan(0),
    );
    await vi.waitFor(
      () =>
        expect(mocks.replaceCategory.mock.calls.map((call) => call[1])).toEqual(
          ["jobs", "faq"],
        ),
      { timeout: 10000 },
    );

    const jobsCall = mocks.replaceCategory.mock.calls[0];
    expect(jobsCall[0]).toBe("7");
    expect(jobsCall[2]).toBe("jobs.yaml");
    expect(jobsCall[3]).toContain("category: jobs");
    // The recruiter does not manage headcount, so no count is ever written.
    expect(jobsCall[3]).not.toContain("vacancies");
  }, 20000);

  it("fills the fields from the brief and leaves the typed name alone", async () => {
    const screen = await render(<ProjectCreate />);
    await screen.getByLabelText("Tên dự án *").fill("Tên tôi tự gõ");
    uploadBrief(screen);

    await vi.waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][1].data.name).toBe("Tên tôi tự gõ");
    await expect
      .element(screen.getByLabelText("Tên gọi khác"))
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
          .element(screen.getByText(/Đã nạp xong 2 phần kiến thức/))
          .toBeVisible(),
      { timeout: 10000 },
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
          .element(screen.getByText(/Đã nạp xong 2 phần kiến thức/))
          .toBeVisible(),
      { timeout: 10000 },
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

  it("re-writes the jobs category when the admin edits the role list", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByText(/Đã nạp xong 2 phần kiến thức/))
          .toBeVisible(),
      { timeout: 10000 },
    );

    await screen
      .getByLabelText("Vị trí tuyển dụng *")
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

  it("refuses to activate a project with no role to advertise", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen, "Tên dự án: Dự án trống\n");
    await screen.getByLabelText("Vị trí tuyển dụng *").fill("   ");

    await vi.waitFor(
      () =>
        expect
          .element(screen.getByRole("button", { name: /Tạo dự án/ }))
          .toBeEnabled(),
      { timeout: 10000 },
    );
    await screen.getByRole("button", { name: /Tạo dự án/ }).click();

    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.stringContaining("ít nhất một vị trí tuyển dụng"),
      { type: "warning" },
    );
  }, 20000);
});
