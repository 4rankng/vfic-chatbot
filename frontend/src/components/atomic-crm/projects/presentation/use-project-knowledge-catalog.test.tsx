// Lifecycle tests for the project knowledge catalog's revision-review poll
// chain.
//
// Covers the FE-21 class of bug: the chain must be cancellable. Tracking a
// second revision cancels the first chain, leaving the page (or switching
// project) stops all polling and fires no stray toasts, and a hidden tab
// never polls.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "vitest-browser-react";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  getCategories: vi.fn(),
  replaceCategory: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("../project-knowledge-service", () => ({
  getProjectKnowledgeCategories: mocks.getCategories,
  replaceProjectKnowledgeCategory: mocks.replaceCategory,
}));

import { useProjectKnowledgeCatalog } from "./use-project-knowledge-catalog";
import type { KnowledgeCategoryStatus } from "../domain/project-knowledge-contracts";

// Mirrors the hook's private POLL_INTERVAL_MS / MAX_POLL_ATTEMPTS.
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 20;

const categoryRow = (
  overrides: Partial<KnowledgeCategoryStatus> = {},
): KnowledgeCategoryStatus => ({
  key: "faq",
  label_vi: "FAQ",
  active_revision_id: "rev-0",
  latest_revision_id: "rev-0",
  status: "ACTIVE",
  ...overrides,
});

// The service resolves a paged envelope, not a bare array.
const catalogResponse = (rows: KnowledgeCategoryStatus[]) => ({
  data: rows,
  total: rows.length,
});

describe("useProjectKnowledgeCatalog", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.values(mocks).forEach((mock) => mock.mockReset());
  });

  afterEach(async () => {
    await cleanup();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("polls until the tracked revision becomes active, then stops and clears processingKey", async () => {
    mocks.getCategories
      .mockResolvedValueOnce(catalogResponse([categoryRow()]))
      .mockResolvedValueOnce(catalogResponse([categoryRow()]))
      .mockResolvedValueOnce(
        catalogResponse([
          {
            ...categoryRow(),
            active_revision_id: "rev-x",
            latest_revision_id: "rev-x",
          },
        ]),
      );
    mocks.replaceCategory.mockResolvedValue({ revision: { id: "rev-x" } });

    const hook = await renderHook(
      (projectId?: string) =>
        useProjectKnowledgeCatalog(projectId ?? "project-1"),
      { initialProps: "project-1" },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(1);

    await hook.act(async () => {
      await hook.result.current.replaceCategory(
        "faq",
        "faq.yaml",
        "faq:\n  - id: cau-hoi",
      );
    });
    expect(hook.result.current.processingKey).toBe("faq");

    // First hop: the revision is still being reviewed.
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(2);
    expect(hook.result.current.processingKey).toBe("faq");

    // Second hop: the revision is live, so the poll ends.
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(3);
    expect(hook.result.current.processingKey).toBeNull();
    expect(mocks.notify).toHaveBeenCalledWith(
      "Dữ liệu mới đã sẵn sàng cho Agent.",
      { type: "success" },
    );
    // The chain is finished: no further hops.
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(3);
  });

  it("reports a failed revision and stops polling", async () => {
    mocks.getCategories
      .mockResolvedValueOnce(catalogResponse([categoryRow()]))
      .mockResolvedValueOnce(
        catalogResponse([
          {
            ...categoryRow(),
            latest_revision_id: "rev-f",
            status: "FAILED",
          },
        ]),
      );
    mocks.replaceCategory.mockResolvedValue({ revision: { id: "rev-f" } });

    const hook = await renderHook(
      (projectId?: string) =>
        useProjectKnowledgeCatalog(projectId ?? "project-1"),
      { initialProps: "project-1" },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await hook.act(async () => {
      await hook.result.current.replaceCategory(
        "faq",
        "faq.yaml",
        "faq:\n  - id: cau-hoi",
      );
    });
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });

    expect(mocks.getCategories).toHaveBeenCalledTimes(2);
    expect(hook.result.current.processingKey).toBeNull();
    expect(mocks.notify).toHaveBeenCalledWith(
      "Nội dung mới có lỗi. Dữ liệu đang dùng không thay đổi.",
      { type: "error" },
    );
  });

  it("a second tracked revision cancels the first chain, so unmount stops all polling", async () => {
    mocks.getCategories.mockResolvedValue(catalogResponse([categoryRow()]));
    mocks.replaceCategory
      .mockResolvedValueOnce({ revision: { id: "rev-a" } })
      .mockResolvedValueOnce({ revision: { id: "rev-b" } });

    const hook = await renderHook(
      (projectId?: string) =>
        useProjectKnowledgeCatalog(projectId ?? "project-1"),
      { initialProps: "project-1" },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(1);

    await hook.act(async () => {
      await hook.result.current.replaceCategory(
        "faq",
        "faq.yaml",
        "faq:\n  - id: cau-hoi",
      );
    });
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(2);

    // A quick replace while the first review is still polling: the new chain
    // must cancel the old one instead of orphaning it.
    await hook.act(async () => {
      await hook.result.current.replaceCategory(
        "faq",
        "faq.yaml",
        "faq:\n  - id: cau-hoi",
      );
    });

    const notifyCallsAtUnmount = mocks.notify.mock.calls.length;
    hook.unmount();
    // Post-unmount there is no React work left, so advance the fake clock
    // directly (act() after unmount corrupts the runner's shared page state).
    await vi.advanceTimersByTimeAsync(MAX_POLL_ATTEMPTS * POLL_INTERVAL_MS);

    // No orphaned chain and no stray toast after leaving the page.
    expect(mocks.getCategories).toHaveBeenCalledTimes(2);
    expect(mocks.notify).toHaveBeenCalledTimes(notifyCallsAtUnmount);
  });

  it("stops polling when the project changes and resets the processing indicator", async () => {
    mocks.getCategories.mockResolvedValue(catalogResponse([categoryRow()]));
    mocks.replaceCategory.mockResolvedValue({ revision: { id: "rev-p" } });

    const hook = await renderHook(
      (projectId?: string) =>
        useProjectKnowledgeCatalog(projectId ?? "project-1"),
      { initialProps: "project-1" },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await hook.act(async () => {
      await hook.result.current.replaceCategory(
        "faq",
        "faq.yaml",
        "faq:\n  - id: cau-hoi",
      );
    });
    expect(hook.result.current.processingKey).toBe("faq");

    await hook.rerender("project-2");
    expect(hook.result.current.processingKey).toBeNull();

    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(MAX_POLL_ATTEMPTS * POLL_INTERVAL_MS);
    });
    // Only the new project's initial load — the old chain is dead.
    expect(mocks.getCategories).toHaveBeenCalledTimes(2);
    expect(mocks.getCategories).toHaveBeenLastCalledWith("project-2");
  });

  it("pauses the poll chain while the tab is hidden and resumes when it is visible again", async () => {
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("visible");
    mocks.getCategories.mockResolvedValue(catalogResponse([categoryRow()]));
    mocks.replaceCategory.mockResolvedValue({ revision: { id: "rev-h" } });

    const hook = await renderHook(
      (projectId?: string) =>
        useProjectKnowledgeCatalog(projectId ?? "project-1"),
      { initialProps: "project-1" },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(1);

    await hook.act(async () => {
      await hook.result.current.replaceCategory(
        "faq",
        "faq.yaml",
        "faq:\n  - id: cau-hoi",
      );
    });

    visibility.mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    // Nothing polls while nothing is watching.
    expect(mocks.getCategories).toHaveBeenCalledTimes(1);

    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(mocks.getCategories).toHaveBeenCalledTimes(2);
    expect(hook.result.current.processingKey).toBe("faq");
  });
});
