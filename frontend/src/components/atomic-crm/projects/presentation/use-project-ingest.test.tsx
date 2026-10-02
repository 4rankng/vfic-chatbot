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

import {
  useProjectIngest,
  type IngestWrite,
  type IngestResult,
} from "./use-project-ingest";
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
  project_training: {
    status,
    completed,
    current,
    planned: ["jobs", "compensation"],
    error: null,
  },
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
  it("uploads one intact source and reports only worker-confirmed categories", async () => {
    mocks.document
      .mockResolvedValueOnce(training("PROCESSING", ["jobs"], "compensation"))
      .mockResolvedValueOnce(training("COMPLETED", ["jobs", "compensation"]));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    expect(mocks.upload).toHaveBeenCalledWith("project-1", source);
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
    expect(await outcome).toEqual({
      ok: true,
      requiresCutover: false,
      activated: ["jobs", "compensation"],
    });
    expect(hook.result.current.state).toEqual({
      phase: "done",
      activated: ["jobs", "compensation"],
    });
    expect(mocks.upload).toHaveBeenCalledTimes(1);
  });

  it("names no category when the ingest has no input at all", async () => {
    // FE-33: the empty-input guard hardcoded failed: "jobs", which rendered
    // as "Chưa xác nhận hoàn tất «Vị trí tuyển dụng»" for a failure that
    // never involved a category.
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", [], undefined);
    });
    expect(await outcome).toEqual({ ok: false });
    expect(hook.result.current.state).toEqual({
      phase: "failed",
      failed: null,
      message: "Không có nội dung kiến thức để nạp.",
      activated: [],
    });
  });

  it("does not claim completion when a worker receipt omits a planned category", async () => {
    mocks.document.mockResolvedValue(training("COMPLETED", ["jobs"]));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook);
    expect(await outcome).toEqual({ ok: false });
    expect(hook.result.current.state).toMatchObject({
      phase: "failed",
      failed: null,
    });
  });

  it("keeps source-wide processing and failures distinct from a category", async () => {
    mocks.document
      .mockResolvedValueOnce(training("PROCESSING"))
      .mockResolvedValueOnce({
        ...training("FAILED"),
        error: "Feature extraction failed",
      });
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", [], source);
    });
    await tick(hook);
    expect(hook.result.current.state).toMatchObject({
      phase: "running",
      current: null,
      items: [
        { key: "jobs", status: "queued" },
        { key: "compensation", status: "queued" },
      ],
    });
    await tick(hook);
    expect(await outcome).toEqual({ ok: false });
    expect(hook.result.current.state).toMatchObject({
      phase: "failed",
      failed: null,
      message: "Feature extraction failed",
    });
  });

  it("keeps completed shadow preparation distinct from live knowledge", async () => {
    const prepared = training("COMPLETED", ["jobs", "compensation"]);
    mocks.document.mockResolvedValue({
      ...prepared,
      project_training: {
        ...prepared.project_training,
        requires_cutover: true,
      },
    });
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook);
    expect(await outcome).toEqual({
      ok: true,
      requiresCutover: true,
      activated: ["jobs", "compensation"],
    });
    expect(hook.result.current.state).toEqual({
      phase: "done",
      activated: ["jobs", "compensation"],
      requiresCutover: true,
    });
    expect(mocks.replace).not.toHaveBeenCalled();

    // Older receipts omit the additive flag. A later live completion must not
    // inherit the earlier source's pending authority transition.
    mocks.document.mockResolvedValue(prepared);
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook);
    expect(await outcome).toEqual({
      ok: true,
      requiresCutover: false,
      activated: ["jobs", "compensation"],
    });
    expect(hook.result.current.state).toEqual({
      phase: "done",
      activated: ["jobs", "compensation"],
    });
  });

  it("settles canceled polling without discarding the durable upload", async () => {
    mocks.document.mockResolvedValue(training("PROCESSING"));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await hook.act(async () => {
      hook.result.current.cancel();
    });
    expect(await outcome).toEqual({ ok: false });
    await tick(hook, 6000);
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(mocks.document).not.toHaveBeenCalled();
  });

  it("retries transient progress-read failures while the worker continues", async () => {
    mocks.document
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce(training("COMPLETED", ["jobs", "compensation"]));
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook, 4000);
    expect(await outcome).toEqual({
      ok: true,
      requiresCutover: false,
      activated: ["jobs", "compensation"],
    });
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
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook);
    expect(await outcome).toEqual({ ok: false });
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
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes, source);
    });
    await tick(hook, 602000);
    expect(await outcome).toEqual({ ok: false });
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(hook.result.current.state).toMatchObject({
      phase: "failed",
      message: expect.stringContaining("hệ thống tiếp tục nạp"),
    });
  });

  it("allows arbitrary layouts and categories absent from browser preview", async () => {
    mocks.document.mockResolvedValue({
      ...training("COMPLETED"),
      project_training: {
        status: "COMPLETED",
        completed: ["benefits", "transportation"],
        planned: ["benefits", "transportation"],
        current: null,
        error: null,
      },
    });
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", [], source);
    });
    await tick(hook);
    expect(await outcome).toEqual({
      ok: true,
      requiresCutover: false,
      activated: ["benefits", "transportation"],
    });
    expect(hook.result.current.state).toMatchObject({
      phase: "done",
      activated: ["benefits", "transportation"],
    });
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("rejects an empty manual knowledge plan before upload", async () => {
    const hook = await renderHook(() => useProjectIngest());
    let outcome: IngestResult = { ok: false };
    await hook.act(async () => {
      outcome = await hook.result.current.ingest("project-1", []);
    });
    expect(outcome).toEqual({ ok: false });
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
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes.slice(0, 1));
    });
    await tick(hook, 4000);
    expect(hook.result.current.state.phase).toBe("running");
    await tick(hook);
    expect(await outcome).toEqual({
      ok: true,
      requiresCutover: false,
      activated: ["jobs"],
    });
    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("resolves cancellation of a manual poll without a later state update", async () => {
    mocks.catalog.mockResolvedValue({ data: [] });
    const hook = await renderHook(() => useProjectIngest());
    let outcome!: Promise<IngestResult>;
    await hook.act(async () => {
      outcome = hook.result.current.ingest("project-1", writes.slice(0, 1));
    });
    await hook.act(async () => {
      hook.result.current.cancel();
    });
    expect(await outcome).toEqual({ ok: false });
    await tick(hook, 6000);
    expect(mocks.catalog).not.toHaveBeenCalled();
  });
});
