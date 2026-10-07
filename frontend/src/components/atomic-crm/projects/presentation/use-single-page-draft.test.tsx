import { cleanup, renderHook } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  load: vi.fn(),
  replace: vi.fn(),
  extract: vi.fn(),
  notify: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));
vi.mock("../project-knowledge-service", () => ({
  getProjectSinglePage: mocks.load,
  replaceProjectSinglePage: mocks.replace,
  extractProjectDocumentText: mocks.extract,
}));
import { useSinglePageDraft } from "./use-single-page-draft";

const options = { isActive: true };
const knowledge = (text: string) => ({ filename: "knowledge.md", text });

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.load.mockResolvedValue(knowledge("Current knowledge"));
  mocks.replace.mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(async () => {
  await cleanup();
  vi.restoreAllMocks();
});

describe("single-page draft ownership", () => {
  it("does not apply an old file read after switching to another project", async () => {
    let finish!: (text: string) => void;
    const file = new File(["Old file"], "old.md", { type: "text/markdown" });
    vi.spyOn(file, "text").mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const hook = await renderHook(
      (projectId = "project-1") => useSinglePageDraft(projectId, options),
      { initialProps: "project-1" },
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    let reading!: Promise<void>;
    await hook.act(() => {
      reading = hook.result.current.readFile(file);
    });
    mocks.load.mockResolvedValueOnce(knowledge("Second project content"));
    await hook.rerender("project-2");
    await expect.poll(() => hook.result.current.loading).toBe(false);
    finish("Old file content");
    await hook.act(async () => {
      await reading;
    });
    expect(hook.result.current.text).toBe("Second project content");
    expect(hook.result.current.filename).toBe("knowledge.md");
  });

  it("does not report or refresh an old save in another project's editor", async () => {
    let finish!: () => void;
    mocks.replace.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const hook = await renderHook(
      (projectId = "project-1") => useSinglePageDraft(projectId, options),
      { initialProps: "project-1" },
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    await hook.act(() => hook.result.current.setText("Saved first project"));
    let saving!: Promise<void>;
    await hook.act(() => {
      saving = hook.result.current.save();
    });
    await hook.rerender("project-2");
    await expect.poll(() => hook.result.current.loading).toBe(false);
    finish();
    await hook.act(async () => {
      await saving;
    });
    expect(hook.result.current.saving).toBe(false);
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(mocks.notify).not.toHaveBeenCalled();
  });

  it("reports an unreadable file without discarding the existing draft", async () => {
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    const file = new File(["Unreadable"], "bad.md");
    vi.spyOn(file, "text").mockRejectedValueOnce(new Error("File unavailable"));
    await hook.act(async () => {
      await hook.result.current.readFile(file);
    });
    expect(hook.result.current.text).toBe("Current knowledge");
    expect(hook.result.current.filename).toBe("knowledge.md");
    expect(mocks.notify).toHaveBeenCalledWith(
      "Không đọc được tệp. Vui lòng thử lại.",
      { type: "error" },
    );
  });

  it("fills the draft from a .docx pick through backend extraction under a .md name", async () => {
    mocks.extract.mockResolvedValueOnce("Nội dung Word đã trích xuất");
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    const file = new File([new Uint8Array([0x50, 0x4b])], "tuyen-dung.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    await hook.act(async () => {
      await hook.result.current.readFile(file);
    });
    expect(mocks.extract).toHaveBeenCalledWith(file);
    expect(hook.result.current.text).toBe("Nội dung Word đã trích xuất");
    expect(hook.result.current.filename).toBe("tuyen-dung.md");
  });

  it("keeps the draft when the backend rejects a .docx pick", async () => {
    mocks.extract.mockRejectedValueOnce(
      new Error("Không đọc được nội dung tệp."),
    );
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    await hook.act(async () => {
      await hook.result.current.readFile(
        new File(["PK"], "hong.docx", { type: "application/zip" }),
      );
    });
    expect(hook.result.current.text).toBe("Current knowledge");
    expect(hook.result.current.filename).toBe("knowledge.md");
    expect(mocks.notify).toHaveBeenCalledWith("Không đọc được nội dung tệp.", {
      type: "error",
    });
  });

  it("still rejects a pick with an unsupported suffix", async () => {
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    await hook.act(async () => {
      await hook.result.current.readFile(
        new File(["%PDF-1.7"], "brief.pdf", { type: "application/pdf" }),
      );
    });
    expect(mocks.extract).not.toHaveBeenCalled();
    expect(hook.result.current.text).toBe("Current knowledge");
    expect(mocks.notify).toHaveBeenCalledWith(
      "Trang kiến thức chỉ nhận file .txt, .md hoặc .docx.",
      { type: "warning" },
    );
  });
});
