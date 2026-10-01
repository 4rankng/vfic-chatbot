import { cleanup, renderHook } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/apiClient";
import type { KnowledgeCategoryStatus } from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCatalog } from "./use-project-knowledge-catalog";

const mocks = vi.hoisted(() => ({
  source: vi.fn(),
  template: vi.fn(),
  notify: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("ra-core", () => ({ useNotify: () => mocks.notify }));
vi.mock("../project-knowledge-service", () => ({
  getProjectKnowledgeCategorySource: mocks.source,
  getProjectKnowledgeCategoryTemplate: mocks.template,
}));
import { useCategoryDraft, type CategoryDraft } from "./use-category-draft";

const source = (revision = "rev-1", content = "PUBLISHED ONE") => ({
  key: "jobs",
  label_vi: "Vị trí",
  revision_id: revision,
  revision_no: 1,
  filename: `${revision}.md`,
  content,
  checksum: "checksum",
  updated_at: "2026-10-01T00:00:00Z",
});
const catalog = (
  revision: string | null = "rev-1",
): ProjectKnowledgeCatalog => ({
  categories: [
    {
      key: "jobs",
      label_vi: "Vị trí",
      active_revision_id: revision,
      latest_revision_id: revision,
      status: revision ? "ACTIVE" : null,
    } satisfies KnowledgeCategoryStatus,
  ],
  processingKey: null,
  reload: vi.fn(),
  replaceCategory: mocks.replace,
});
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.source.mockResolvedValue(source());
  mocks.template.mockResolvedValue({
    key: "jobs",
    label_vi: "Vị trí",
    filename: "jobs-template.md",
    content: "BLANK TEMPLATE",
  });
  mocks.replace.mockResolvedValue(undefined);
});
afterEach(async () => {
  await cleanup();
  vi.restoreAllMocks();
});

const loaded = async (hook: { result: { current: CategoryDraft } }) => {
  await vi.waitFor(() => expect(hook.result.current.loading).toBe(false));
};
describe("category draft stays grounded in the published source", () => {
  it("loads the first published revision without requiring a category switch", async () => {
    mocks.source.mockRejectedValueOnce(new ApiError(404, "Chưa có dữ liệu"));
    const hook = await renderHook(
      (rows: ProjectKnowledgeCatalog = catalog()) =>
        useCategoryDraft("project-1", "jobs", rows),
      { initialProps: catalog(null) },
    );
    await loaded(hook);
    expect(hook.result.current.hasCurrentSource).toBe(false);
    mocks.source.mockResolvedValue(source("rev-2", "NEW PUBLISHED"));
    await hook.rerender(catalog("rev-2"));
    await vi.waitFor(() =>
      expect(hook.result.current.content).toBe("NEW PUBLISHED"),
    );
    expect(hook.result.current.hasCurrentSource).toBe(true);
  });

  it("refreshes source text and filename when the active revision changes", async () => {
    const hook = await renderHook(
      (rows: ProjectKnowledgeCatalog = catalog()) =>
        useCategoryDraft("project-1", "jobs", rows),
      { initialProps: catalog() },
    );
    await loaded(hook);
    mocks.source.mockResolvedValue(source("rev-2", "NEW PUBLISHED"));
    await hook.rerender(catalog("rev-2"));
    await vi.waitFor(() =>
      expect(hook.result.current.content).toBe("NEW PUBLISHED"),
    );
    expect(hook.result.current.filename).toBe("rev-2.md");
  });

  it("retains unsaved edits during publication and cancels back to the new source", async () => {
    const hook = await renderHook(
      (rows: ProjectKnowledgeCatalog = catalog()) =>
        useCategoryDraft("project-1", "jobs", rows),
      { initialProps: catalog() },
    );
    await loaded(hook);
    await hook.act(() => {
      hook.result.current.startEditing();
      hook.result.current.setContent("MY UNSAVED EDIT");
    });
    mocks.source.mockResolvedValue(source("rev-2", "NEW PUBLISHED"));
    await hook.rerender(catalog("rev-2"));
    await vi.waitFor(() => expect(mocks.source).toHaveBeenCalledTimes(2));
    await loaded(hook);
    expect(hook.result.current.isEditing).toBe(true);
    expect(hook.result.current.content).toBe("MY UNSAVED EDIT");
    await hook.act(() => hook.result.current.cancelEditing());
    expect(hook.result.current.content).toBe("NEW PUBLISHED");
  });

  it("keeps accepted but unreviewed content separate from the source used by the bot", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const hook = await renderHook(() =>
      useCategoryDraft("project-1", "jobs", catalog()),
    );
    await loaded(hook);
    await hook.act(() => {
      hook.result.current.startEditing();
      hook.result.current.setContent("UNREVIEWED EDIT");
    });
    await hook.act(async () => hook.result.current.save());
    expect(hook.result.current.isEditing).toBe(false);
    expect(hook.result.current.content).toBe("PUBLISHED ONE");
    await hook.act(() => hook.result.current.startEditing());
    expect(hook.result.current.content).toBe("UNREVIEWED EDIT");
  });

  it("blocks replacing an unknown source after a read failure and supports retry", async () => {
    mocks.source.mockRejectedValueOnce(
      new ApiError(503, "Chưa đọc được nguồn hiện tại"),
    );
    const hook = await renderHook(() =>
      useCategoryDraft("project-1", "jobs", catalog()),
    );
    await loaded(hook);
    expect(hook.result.current.loadFailed).toBe(true);
    await hook.act(() => {
      hook.result.current.startEditing();
      hook.result.current.setContent("BLANK OVERWRITE");
    });
    await hook.act(async () => hook.result.current.save());
    expect(mocks.replace).not.toHaveBeenCalled();
    await hook.act(async () => hook.result.current.reload());
    expect(hook.result.current.loadFailed).toBe(false);
    expect(hook.result.current.content).toBe("PUBLISHED ONE");
  });

  it("submits one revision when save is invoked twice before React updates", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const pending = deferred<void>();
    mocks.replace.mockReturnValue(pending.promise);
    const hook = await renderHook(() =>
      useCategoryDraft("project-1", "jobs", catalog()),
    );
    await loaded(hook);
    await hook.act(() => {
      hook.result.current.startEditing();
      hook.result.current.setContent("REVIEWED EDIT");
    });
    let first!: Promise<void>;
    let second!: Promise<void>;
    await hook.act(() => {
      first = hook.result.current.save();
      second = hook.result.current.save();
    });
    expect(mocks.replace).toHaveBeenCalledTimes(1);
    await hook.act(async () => {
      pending.resolve();
      await Promise.all([first, second]);
    });
    expect(hook.result.current.saving).toBe(false);
  });

  it("allows retry after a rejected revision write", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.replace.mockRejectedValueOnce(new Error("write rejected"));
    const hook = await renderHook(() =>
      useCategoryDraft("project-1", "jobs", catalog()),
    );
    await loaded(hook);
    await hook.act(() => {
      hook.result.current.startEditing();
      hook.result.current.setContent("REVIEWED EDIT");
    });
    await hook.act(async () => hook.result.current.save());
    expect(hook.result.current.saving).toBe(false);
    expect(hook.result.current.isEditing).toBe(true);
    await hook.act(async () => hook.result.current.save());
    expect(mocks.replace).toHaveBeenCalledTimes(2);
    expect(hook.result.current.isEditing).toBe(false);
  });

  it("does not let a save for the previous project close the current editor", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const pending = deferred<void>();
    mocks.replace.mockReturnValue(pending.promise);
    const hook = await renderHook(
      (projectId = "project-1") =>
        useCategoryDraft(projectId, "jobs", catalog()),
      { initialProps: "project-1" },
    );
    await loaded(hook);
    await hook.act(() => {
      hook.result.current.startEditing();
      hook.result.current.setContent("OLD PROJECT EDIT");
    });
    let saving!: Promise<void>;
    await hook.act(() => {
      saving = hook.result.current.save();
    });
    mocks.source.mockResolvedValue(source("rev-1", "SECOND PROJECT"));
    await hook.rerender("project-2");
    await loaded(hook);
    await hook.act(() => {
      hook.result.current.startEditing();
      hook.result.current.setContent("NEW PROJECT EDIT");
    });
    await hook.act(async () => {
      pending.resolve();
      await saving;
    });
    expect(hook.result.current.isEditing).toBe(true);
    expect(hook.result.current.content).toBe("NEW PROJECT EDIT");
    await hook.act(() => hook.result.current.cancelEditing());
    expect(hook.result.current.content).toBe("SECOND PROJECT");
  });
});
