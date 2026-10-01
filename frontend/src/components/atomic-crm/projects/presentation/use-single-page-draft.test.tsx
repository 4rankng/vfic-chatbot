import { cleanup, renderHook } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  load: vi.fn(),
  sync: vi.fn(),
  replace: vi.fn(),
  notify: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));
vi.mock("../project-knowledge-service", () => ({
  getProjectSinglePage: mocks.load,
  listSinglePageExternalSources: mocks.sync,
  replaceProjectSinglePage: mocks.replace,
}));
import { useSinglePageDraft } from "./use-single-page-draft";

const options = { isActive: true, canManageSources: true };
const knowledge = (text: string) => ({ filename: "knowledge.md", text });

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.load.mockResolvedValue(knowledge("Current knowledge"));
  mocks.sync.mockResolvedValue([]);
  mocks.replace.mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(async () => {
  await cleanup();
  vi.restoreAllMocks();
});

describe("single-page draft ownership", () => {
  it("preserves a local edit when a synchronized source publishes new content", async () => {
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    await hook.act(() => hook.result.current.setText("My unsaved edit"));
    mocks.load.mockResolvedValue(knowledge("New sheet content"));
    await hook.act(() => hook.result.current.handleSynchronized());
    await expect.poll(() => hook.result.current.refreshing).toBe(false);
    expect(hook.result.current.text).toBe("My unsaved edit");
    expect(hook.result.current.remoteChanged).toBe(true);
    await hook.act(() => hook.result.current.handleSynchronized());
    await expect.poll(() => hook.result.current.refreshing).toBe(false);
    expect(hook.result.current.remoteChanged).toBe(true);
    await hook.act(() => hook.result.current.discardChanges());
    expect(hook.result.current.text).toBe("New sheet content");
  });

  it("clears a source update warning when the local draft matches it", async () => {
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    await hook.act(() => hook.result.current.setText("My unsaved edit"));
    mocks.load.mockResolvedValueOnce(knowledge("New sheet content"));
    await hook.act(() => hook.result.current.handleSynchronized());
    await expect.poll(() => hook.result.current.refreshing).toBe(false);
    await hook.act(() => hook.result.current.setText("New sheet content"));
    expect(hook.result.current.remoteChanged).toBe(false);
  });

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

  it("finishes a foreground retry when a newer background sync supersedes it", async () => {
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    let finish!: (page: ReturnType<typeof knowledge>) => void;
    mocks.load.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    let retry!: Promise<void>;
    await hook.act(() => {
      retry = hook.result.current.reload();
    });
    mocks.load.mockResolvedValueOnce(knowledge("Synchronized content"));
    await hook.act(() => hook.result.current.handleSynchronized());
    await expect.poll(() => hook.result.current.refreshing).toBe(false);
    expect(hook.result.current.loading).toBe(false);
    finish(knowledge("Stale retry response"));
    await hook.act(async () => {
      await retry;
    });
    expect(hook.result.current.text).toBe("Synchronized content");
  });

  it("waits until saving finishes before refreshing a synchronized source", async () => {
    const hook = await renderHook(() =>
      useSinglePageDraft("project-1", options),
    );
    await expect.poll(() => hook.result.current.loading).toBe(false);
    let finish!: () => void;
    mocks.replace.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    let save!: Promise<void>;
    await hook.act(() => {
      save = hook.result.current.save();
    });
    await hook.act(() => hook.result.current.handleSynchronized());
    expect(mocks.load).toHaveBeenCalledTimes(1);
    mocks.load.mockResolvedValueOnce(knowledge("Newer synchronized content"));
    finish();
    await hook.act(async () => {
      await save;
    });
    await expect.poll(() => hook.result.current.refreshing).toBe(false);
    expect(mocks.load).toHaveBeenCalledTimes(2);
    expect(hook.result.current.text).toBe("Newer synchronized content");
  });
});
