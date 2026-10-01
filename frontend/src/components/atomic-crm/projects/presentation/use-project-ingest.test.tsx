import { cleanup, renderHook } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  upload: vi.fn(),
  document: vi.fn(),
  replace: vi.fn(),
  catalog: vi.fn(),
}));
vi.mock("../project-knowledge-service", () => ({
  uploadProjectDocument: mocks.upload,
  getProjectTrainingDocument: mocks.document,
  replaceProjectKnowledgeCategory: mocks.replace,
  getProjectKnowledgeCategories: mocks.catalog,
}));

import { useProjectIngest, type IngestWrite } from "./use-project-ingest";
const writes: IngestWrite[] = [
  { key: "jobs", filename: "jobs.md", content: "grounded jobs" },
  {
    key: "compensation",
    filename: "compensation.md",
    content: "grounded salary",
  },
];
const source = new File(["brief"], "brief.txt", { type: "text/plain" });
const training = (
  status: string,
  completed: string[] = [],
  current: string | null = null,
) => ({
  id: "document-1",
  status: "PROCESSING",
  error: null,
  project_training: { status, completed, current, error: null },
});

beforeEach(() => {
  vi.useFakeTimers();
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.upload.mockResolvedValue({ id: "document-1" });
  mocks.replace.mockResolvedValue({ revision: { id: "new-jobs" } });
});
afterEach(async () => {
  await cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const tick = async (
  hook: Awaited<ReturnType<typeof renderHook>>,
  milliseconds = 2000,
) => {
  await hook.act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
};

describe("useProjectIngest durable source upload", () => {
  it("uploads one source with its plan and reports only worker-confirmed categories", async () => {
    mocks.document
      .mockResolvedValueOnce(training("PROCESSING", ["jobs"], "compensation"))
      .mockResolvedValueOnce(training("COMPLETED", ["jobs", "compensation"]));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    expect(mocks.upload).toHaveBeenCalledWith("project-1", source, writes);
    expect(mocks.replace).not.toHaveBeenCalled();
    await tick(hook);
    expect(hook.result.current.state).toMatchObject({
      phase: "running",
      current: "compensation",
      activated: ["jobs"],
      items: [
        { key: "jobs", status: "active" },
        { key: "compensation", status: "processing" },
      ],
    });
    await tick(hook);
    expect(await outcome).toBe(true);
    expect(hook.result.current.state).toEqual({
      phase: "done",
      activated: ["jobs", "compensation"],
    });
    expect(mocks.upload).toHaveBeenCalledTimes(1);
  });

  it("does not claim completion when a worker receipt omits a planned category", async () => {
    mocks.document.mockResolvedValue(training("COMPLETED", ["jobs"]));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook);
    expect(await outcome).toBe(false);
    expect(hook.result.current.state).toMatchObject({
      phase: "failed",
      failed: "compensation",
    });
  });

  it("settles canceled polling without discarding the durable upload", async () => {
    mocks.document.mockResolvedValue(training("PROCESSING"));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await hook.act(async () => {
      hook.result.current.cancel();
    });
    expect(await outcome).toBe(false);
    await tick(hook, 6000);
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(mocks.document).not.toHaveBeenCalled();
  });

  it("retries transient progress-read failures while the worker continues", async () => {
    mocks.document
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce(training("COMPLETED", ["jobs", "compensation"]));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook, 4000);
    expect(await outcome).toBe(true);
    expect(mocks.upload).toHaveBeenCalledTimes(1);
  });

  it("preserves the worker's category and reason on failure", async () => {
    mocks.document.mockResolvedValue({
      ...training("FAILED", ["jobs"], "compensation"),
      project_training: {
        status: "FAILED",
        completed: ["jobs"],
        current: "compensation",
        error: "Invalid salary data",
      },
    });
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook);
    expect(await outcome).toBe(false);
    expect(hook.result.current.state).toMatchObject({
      phase: "failed",
      failed: "compensation",
      message: "Invalid salary data",
      activated: ["jobs"],
    });
  });

  it("keeps the durable source after the observation budget expires", async () => {
    mocks.document.mockResolvedValue(training("PROCESSING"));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook, 602000);
    expect(await outcome).toBe(false);
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(hook.result.current.state).toMatchObject({
      phase: "failed",
      message: expect.stringContaining("hệ thống tiếp tục nạp"),
    });
  });

  it("rejects an empty knowledge plan before upload", async () => {
    const hook = await renderHook(() => useProjectIngest());
    let outcome = true;
    await hook.act(async () => {
      outcome = await hook.result.current.ingest("project-1", [], source);
    });
    expect(outcome).toBe(false);
    expect(mocks.upload).not.toHaveBeenCalled();
    expect(hook.result.current.state).toMatchObject({ phase: "failed" });
  });
});

describe("useProjectIngest manual revision confirmation", () => {
  it("waits through missing and stale rows until its exact revision is active", async () => {
    mocks.catalog
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({
        data: [
          { key: "jobs", active_revision_id: "old-jobs", status: "ACTIVE" },
        ],
      })
      .mockResolvedValueOnce({
        data: [
          { key: "jobs", active_revision_id: "new-jobs", status: "ACTIVE" },
        ],
      });
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes.slice(0, 1));
    });
    await tick(hook, 4000);
    expect(hook.result.current.state.phase).toBe("running");
    await tick(hook);
    expect(await outcome).toBe(true);
    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("resolves cancellation of a manual poll without a later state update", async () => {
    mocks.catalog.mockResolvedValue({ data: [] });
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<boolean>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes.slice(0, 1));
    });
    await hook.act(async () => {
      hook.result.current.cancel();
    });
    expect(await outcome).toBe(false);
    await tick(hook, 6000);
    expect(mocks.catalog).not.toHaveBeenCalled();
  });
});
