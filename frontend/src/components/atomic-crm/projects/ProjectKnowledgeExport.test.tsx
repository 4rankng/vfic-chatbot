import { cleanup, render } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  export: vi.fn(),
  template: vi.fn(),
  notify: vi.fn(),
}));
vi.mock("ra-core", () => ({ useNotify: () => mocks.notify }));
vi.mock("./project-knowledge-service", () => ({
  getProjectKnowledgeExport: mocks.export,
  getProjectKnowledgeFullTemplate: mocks.template,
}));

import {
  ProjectKnowledgeExport,
  ProjectKnowledgeTemplate,
} from "./ProjectKnowledgeExport";

const saved = {
  filename: "kb-lg-display.md",
  content: "# LG Display\nKiến thức đã lưu.",
};
const blobs: Blob[] = [];
const downloads: Array<{ filename: string; href: string; attached: boolean }> =
  [];
const deferred = () => {
  let resolve!: (value: typeof saved) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<typeof saved>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
};

beforeEach(() => {
  mocks.export.mockReset().mockResolvedValue(saved);
  mocks.template.mockReset().mockResolvedValue({
    filename: "mau-kb-du-an.md",
    content: "# Mẫu KB\n## Thông tin dự án",
  });
  mocks.notify.mockReset();
  blobs.length = 0;
  downloads.length = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    blobs.push(blob as Blob);
    return "blob:project-knowledge-test";
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    downloads.push({
      filename: this.download,
      href: this.href,
      attached: this.isConnected,
    });
  });
});

afterEach(async () => {
  await cleanup();
  vi.restoreAllMocks();
});

describe("ProjectKnowledgeExport", () => {
  it("downloads the text template separately and handles its pending failure", async () => {
    const request = deferred();
    mocks.template.mockReturnValueOnce(request.promise);
    const screen = await render(
      <ProjectKnowledgeTemplate projectId="project-1" />,
    );
    const button = screen.getByRole("button", { name: "Tải mẫu KB" });
    await button.click();
    await expect.element(button).toBeDisabled();
    request.reject(new Error("Template request failed"));
    await expect.poll(() => mocks.notify.mock.calls.length).toBe(1);
    expect(mocks.notify).toHaveBeenCalledWith(
      "Chưa tải được mẫu KB. Vui lòng thử lại.",
      { type: "error" },
    );
    expect(downloads).toEqual([]);
    await expect.element(button).not.toBeDisabled();
    await button.click();
    await expect.poll(() => downloads.length).toBe(1);
    expect(mocks.template).toHaveBeenLastCalledWith(
      "project-1",
      expect.any(AbortSignal),
    );
    expect(mocks.export).not.toHaveBeenCalled();
    expect(downloads[0].filename).toBe("mau-kb-du-an.md");
    expect(await blobs[0].text()).toBe("# Mẫu KB\n## Thông tin dự án");
    await expect
      .poll(() => vi.mocked(URL.revokeObjectURL).mock.calls.length)
      .toBe(1);
  });

  it("downloads the server's saved Markdown and releases the temporary attachment", async () => {
    const screen = await render(
      <ProjectKnowledgeExport projectId="project-1" />,
    );
    await screen.getByRole("button", { name: "Xuất KB" }).click();

    await expect.poll(() => downloads.length).toBe(1);
    expect(mocks.export).toHaveBeenCalledWith(
      "project-1",
      expect.any(AbortSignal),
    );
    expect(downloads[0]).toEqual({
      filename: saved.filename,
      href: "blob:project-knowledge-test",
      attached: true,
    });
    expect(blobs[0].type).toBe("text/markdown;charset=utf-8");
    expect(await blobs[0].text()).toBe(saved.content);
    expect(document.querySelector('a[download="kb-lg-display.md"]')).toBeNull();
    await expect
      .poll(() => vi.mocked(URL.revokeObjectURL).mock.calls.length)
      .toBe(1);
    await expect
      .element(screen.getByText("KB đang sử dụng · Markdown (.md)"))
      .toBeVisible();
    expect(mocks.notify).not.toHaveBeenCalled();
  });

  it("allows only one pending export and enables retry after a Vietnamese failure", async () => {
    const request = deferred();
    mocks.export.mockReturnValueOnce(request.promise);
    const screen = await render(
      <ProjectKnowledgeExport projectId="project-1" />,
    );
    const button = screen.getByRole("button", { name: "Xuất KB" });
    (button.element() as HTMLButtonElement).click();
    (button.element() as HTMLButtonElement).click();
    await expect.element(button).toBeDisabled();
    expect(mocks.export).toHaveBeenCalledTimes(1);
    request.reject(new Error("Network unavailable"));
    await expect.poll(() => mocks.notify.mock.calls.length).toBe(1);
    expect(mocks.notify).toHaveBeenCalledWith(
      "Chưa xuất được KB. Vui lòng thử lại.",
      { type: "error" },
    );
    expect(downloads).toEqual([]);
    expect(blobs).toEqual([]);
    await expect.element(button).not.toBeDisabled();
    await button.click();
    await expect.poll(() => downloads.length).toBe(1);
    await expect
      .poll(() => vi.mocked(URL.revokeObjectURL).mock.calls.length)
      .toBe(1);
  });

  it("does not create a file for an empty response", async () => {
    mocks.export.mockResolvedValueOnce({
      filename: saved.filename,
      content: " \n",
    });
    const screen = await render(
      <ProjectKnowledgeExport projectId="project-1" />,
    );
    await screen.getByRole("button", { name: "Xuất KB" }).click();
    await expect.poll(() => mocks.notify.mock.calls.length).toBe(1);
    expect(mocks.notify).toHaveBeenCalledWith(
      "Dự án chưa có kiến thức đã lưu để xuất.",
      { type: "error" },
    );
    expect(blobs).toEqual([]);
    expect(downloads).toEqual([]);
  });

  it("cancels the previous project without downloading it or clearing the next project's busy state", async () => {
    const first = deferred();
    const second = deferred();
    mocks.export
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const screen = await render(
      <ProjectKnowledgeExport projectId="project-1" />,
    );
    await screen.getByRole("button", { name: "Xuất KB" }).click();
    const firstSignal = mocks.export.mock.calls[0][1] as AbortSignal;
    await screen.rerender(<ProjectKnowledgeExport projectId="project-2" />);
    expect(firstSignal.aborted).toBe(true);
    const button = screen.getByRole("button", { name: "Xuất KB" });
    await expect.element(button).not.toBeDisabled();
    await button.click();
    first.resolve(saved);
    await first.promise;
    expect(downloads).toEqual([]);
    expect(mocks.notify).not.toHaveBeenCalled();
    await expect.element(button).toBeDisabled();

    second.resolve({
      filename: "kb-project-2.md",
      content: "Second project saved knowledge",
    });
    await expect.poll(() => downloads.length).toBe(1);
    expect(mocks.export).toHaveBeenLastCalledWith(
      "project-2",
      expect.any(AbortSignal),
    );
    expect(downloads[0].filename).toBe("kb-project-2.md");
    expect(await blobs[0].text()).toBe("Second project saved knowledge");
    await expect
      .poll(() => vi.mocked(URL.revokeObjectURL).mock.calls.length)
      .toBe(1);
  });

  it("discards a late successful response after unmount", async () => {
    const request = deferred();
    mocks.export.mockReturnValueOnce(request.promise);
    const screen = await render(
      <ProjectKnowledgeExport projectId="project-1" />,
    );
    await screen.getByRole("button", { name: "Xuất KB" }).click();
    const signal = mocks.export.mock.calls[0][1] as AbortSignal;
    await screen.unmount();
    expect(signal.aborted).toBe(true);
    request.resolve(saved);
    await request.promise;
    expect(downloads).toEqual([]);
    expect(blobs).toEqual([]);
    expect(mocks.notify).not.toHaveBeenCalled();
  });

  it("does not report a cancelled failure in the next project", async () => {
    const request = deferred();
    mocks.export.mockReturnValueOnce(request.promise);
    const screen = await render(
      <ProjectKnowledgeExport projectId="project-1" />,
    );
    await screen.getByRole("button", { name: "Xuất KB" }).click();
    await screen.rerender(<ProjectKnowledgeExport projectId="project-2" />);
    request.reject(new Error("Old request failed"));
    await expect(request.promise).rejects.toThrow("Old request failed");
    expect(mocks.notify).not.toHaveBeenCalled();
    expect(downloads).toEqual([]);
    await expect
      .element(screen.getByRole("button", { name: "Xuất KB" }))
      .not.toBeDisabled();
  });
});
