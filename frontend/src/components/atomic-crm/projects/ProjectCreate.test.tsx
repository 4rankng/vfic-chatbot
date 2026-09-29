import type { ReactNode } from "react";
import { render, type RenderResult } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The `await import("react-hook-form")` calls inside the vi.mock factories are
// the one case a static import cannot serve: a mock factory runs through the
// module registry, so the real module has to be fetched at factory time.
const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
  create: vi.fn(),
  notify: vi.fn(),
  replaceCategory: vi.fn(),
  replaceSinglePage: vi.fn(),
  createFaq: vi.fn(),
}));

/** Vitest's browser render result, named by the library rather than inferred
 *  from the call — the helper must not couple to `render`'s implementation. */
type BriefForm = RenderResult;

vi.mock("ra-core", async () => {
  // react-admin's `Form` is a react-hook-form `FormProvider`, and the brief
  // import writes into it with `setValue`. A plain <form> stub would throw here
  // — and would hide the very wiring this feature depends on.
  const { FormProvider, useForm } = await import("react-hook-form");

  return {
    CreateBase: ({ children }: { children: ReactNode }) => <>{children}</>,
    Form: ({
      children,
      onSubmit,
    }: {
      children: ReactNode;
      onSubmit: (data: Record<string, unknown>) => void;
    }) => {
      const form = useForm();
      return (
        <FormProvider {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>{children}</form>
        </FormProvider>
      );
    },
    useDataProvider: () => ({ create: mocks.create }),
    useNotify: () => mocks.notify,
    useRedirect: () => mocks.redirect,
  };
});

vi.mock("@/components/admin/text-input", async () => {
  const { useFormContext } = await import("react-hook-form");

  return {
    TextInput: ({ source, label }: { source: string; label: string }) => {
      const { register } = useFormContext();
      return <input aria-label={label} {...register(source)} />;
    },
  };
});

vi.mock("./project-knowledge-service", () => ({
  createProjectFaq: mocks.createFaq,
  replaceProjectKnowledgeCategory: mocks.replaceCategory,
  replaceProjectSinglePage: mocks.replaceSinglePage,
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
const uploadBrief = (screen: BriefForm) => {
  const input =
    screen.container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("the brief import renders no file input");
  const file = new File([BRIEF], "phiếu 4P.md", { type: "text/markdown" });
  // A real `FileList` — `input.files` rejects a plain array.
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
};

describe("ProjectCreate", () => {
  beforeEach(() => {
    mocks.redirect.mockReset();
    mocks.create.mockReset();
    mocks.notify.mockReset();
    mocks.replaceCategory.mockReset();
    mocks.replaceSinglePage.mockReset();
    mocks.createFaq.mockReset();
    mocks.create.mockResolvedValue({ data: { id: "7" } });
    mocks.replaceCategory.mockResolvedValue({});
    mocks.replaceSinglePage.mockResolvedValue({});
    mocks.createFaq.mockResolvedValue({});
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

  it("presents a clear knowledge choice and labels conditional fields", async () => {
    const screen = await render(<ProjectCreate />);
    const directMode = screen.getByRole("radio", {
      name: /Một nội dung/,
    });

    await expect.element(directMode).not.toBeChecked();
    await directMode.click();
    await expect.element(directMode).toBeChecked();
    expect(
      directMode.element().closest("[data-selected='true']"),
    ).not.toBeNull();

    await expect
      .element(
        screen.getByRole("heading", { name: "Giúp ứng viên tìm đúng dự án" }),
      )
      .toBeVisible();
    await expect.element(screen.getByLabelText("Tóm tắt *")).toBeVisible();
    await expect.element(screen.getByLabelText("Địa điểm *")).toBeVisible();
    await expect
      .element(screen.getByLabelText("Vị trí tuyển dụng"))
      .toBeVisible();
  });
});

describe("ProjectCreate — nhập phiếu thông tin từ tệp", () => {
  beforeEach(() => {
    mocks.redirect.mockReset();
    mocks.create.mockReset();
    mocks.notify.mockReset();
    mocks.replaceCategory.mockReset();
    mocks.replaceSinglePage.mockReset();
    mocks.createFaq.mockReset();
    mocks.create.mockResolvedValue({ data: { id: "7" } });
    mocks.replaceCategory.mockResolvedValue({});
    mocks.replaceSinglePage.mockResolvedValue({});
    mocks.createFaq.mockResolvedValue({});
  });

  it("offers a file picker on the create form", async () => {
    const screen = await render(<ProjectCreate />);
    await expect
      .element(
        screen.getByRole("heading", { name: "Đã có sẵn phiếu thông tin?" }),
      )
      .toBeVisible();
    await expect
      .element(screen.getByLabelText("Chọn tệp phiếu thông tin dự án"))
      .toBeVisible();
  });

  it("fills the identity fields and picks the knowledge mode from the brief", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    // The identity fields are react-admin's own inputs, written through the
    // form context — this is the assertion that would fail if the import only
    // filled local state.
    await expect
      .element(screen.getByLabelText("Tên dự án"))
      .toHaveValue("4P ELECTRONIC");
    await expect
      .element(screen.getByLabelText("Mã dự án"))
      .toHaveValue("4p-electronic");
    // Three sections in the brief is enough to choose the by-category mode.
    await expect
      .element(screen.getByRole("radio", { name: /Theo danh mục/ }))
      .toBeChecked();
    // `Tên gọi khác` renders in both modes, so it is asserted here.
    await expect
      .element(screen.getByLabelText("Tên gọi khác"))
      .toHaveValue("4P Electronics, 4P Hải Phòng");
  });

  it("fills the discovery card fields when the recruiter keeps one-page mode", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    // The discovery card only exists in "Một nội dung" — the product's own
    // rule, unchanged by this feature. Switching to it reveals the fields the
    // brief already filled, so the recruiter still types nothing.
    await screen.getByRole("radio", { name: /Một nội dung/ }).click();
    await expect
      .element(screen.getByLabelText("Tóm tắt *"))
      .toHaveValue("Lắp ráp linh kiện bảng mạch.");
    await expect
      .element(screen.getByLabelText("Địa điểm *"))
      .toHaveValue("Hải Phòng");
    await expect
      .element(screen.getByLabelText("Vị trí tuyển dụng"))
      .toHaveValue("Công nhân, SMT, PCBA");
    await expect
      .element(screen.getByLabelText("Điểm nổi bật"))
      .toHaveValue("Không yêu cầu bằng cấp., Đóng BHXH đầy đủ.");
  });

  it("reports what it read and what the brief did not cover", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    // Reading the file is async, so the summary is not there on the tick the
    // change event fires — assert against the text once it lands.
    await expect
      .element(screen.getByTestId("project-brief-summary"))
      .toHaveTextContent(/phiếu 4P\.md/);
    // jobs + compensation + faq came from the brief; the rest did not.
    await expect
      .element(screen.getByTestId("project-brief-summary"))
      .toHaveTextContent(/3\/12 phần kiến thức/);
    await expect
      .element(screen.getByTestId("project-brief-summary"))
      .toHaveTextContent(/Đưa đón & lịch xe/);
  });

  it("seeds the FAQ category as typed YAML and names what still needs a human", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await screen.getByRole("button", { name: "Tạo dự án" }).click();

    await expect
      .poll(() => mocks.replaceCategory.mock.calls.length)
      .toBeGreaterThan(0);
    // The RAG categories are typed YAML, not prose: the API rejects a `.md`
    // body outright. Only the FAQ is derivable from the file.
    const [projectId, key, filename, content] =
      mocks.replaceCategory.mock.calls[0];
    expect(projectId).toBe("7");
    expect(key).toBe("faq");
    expect(filename).toBe("faq.yaml");
    expect(content).toContain("category: faq");
    expect(content).toContain("Công ty tuyển việc gì?");
    // Nothing is invented for a category whose typed fields the brief lacks.
    expect(mocks.replaceCategory.mock.calls.length).toBe(1);
    expect(mocks.createFaq).not.toHaveBeenCalled();
    // …and the recruiter is told, not left to find an empty category later.
    await expect.poll(() => mocks.notify.mock.calls.length).toBeGreaterThan(0);
    const messages = mocks.notify.mock.calls.map((call) => call[0]);
    expect(
      messages.some(
        (message: string) =>
          typeof message === "string" && message.includes("cần nhập tay"),
      ),
    ).toBe(true);
    expect(mocks.redirect).toHaveBeenCalledWith("edit", "projects", "7");
  });

  it("saves the whole brief as one page when the recruiter picks one-page mode", async () => {
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);
    await screen.getByRole("radio", { name: /Một nội dung/ }).click();

    await screen.getByRole("button", { name: "Tạo dự án" }).click();

    await expect
      .poll(() => mocks.replaceSinglePage.mock.calls.length)
      .toBeGreaterThan(0);
    const [projectId, filename, text] = mocks.replaceSinglePage.mock.calls[0];
    expect(projectId).toBe("7");
    expect(filename).toBe("phiếu 4P.md");
    expect(text).toContain("4P ELECTRONIC");
    // One page is the whole document, so no category is written.
    expect(mocks.replaceCategory).not.toHaveBeenCalled();
  });

  it("still creates the project when a knowledge write fails, and says so", async () => {
    mocks.replaceCategory.mockRejectedValue(new Error("boom"));
    const screen = await render(<ProjectCreate />);
    uploadBrief(screen);

    await screen.getByRole("button", { name: "Tạo dự án" }).click();

    await expect.poll(() => mocks.notify.mock.calls.length).toBeGreaterThan(0);
    const messages = mocks.notify.mock.calls.map((call) => call[0]);
    expect(
      messages.some(
        (message: string) =>
          typeof message === "string" && message.includes("chưa lưu được"),
      ),
    ).toBe(true);
    // The project is not lost to a knowledge failure.
    expect(mocks.redirect).toHaveBeenCalledWith("edit", "projects", "7");
  });
});
