import { cleanup, renderHook } from "vitest-browser-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Project } from "../../types";

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  notify: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
  useRefresh: () => mocks.refresh,
}));
vi.mock("../project-knowledge-service", () => ({
  updateProjectDiscoveryCard: mocks.update,
}));
import { useDiscoveryCardDraft } from "./use-discovery-card-draft";

const project = (id = "project-1", summary = "FIRST PROJECT"): Project => ({
  id,
  slug: id,
  name: id,
  is_active: true,
  knowledge_mode: "DIRECT_CONTEXT",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  index_card: {
    summary,
    location: "Hải Phòng",
    eligibility: ["Từ 18 tuổi"],
    highlights: ["Xe đưa đón"],
  },
});
beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  mocks.update.mockResolvedValue(project());
});
afterEach(async () => {
  await cleanup();
});

describe("discovery card publication", () => {
  it("preserves worker criteria which the form does not edit", async () => {
    const hook = await renderHook(() => useDiscoveryCardDraft(project()));
    await hook.act(() =>
      hook.result.current.setField("summary", "UPDATED SUMMARY"),
    );
    await hook.act(async () => hook.result.current.save());
    expect(mocks.update.mock.calls[0][1].discovery_card).not.toHaveProperty(
      "eligibility",
    );
  });

  it("submits one card update when save is invoked twice before React updates", async () => {
    let complete!: () => void;
    mocks.update.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        }),
    );
    const hook = await renderHook(() => useDiscoveryCardDraft(project()));
    let first!: Promise<void>;
    let second!: Promise<void>;
    await hook.act(() => {
      first = hook.result.current.save();
      second = hook.result.current.save();
    });
    expect(mocks.update).toHaveBeenCalledTimes(1);
    await hook.act(async () => {
      complete();
      await Promise.all([first, second]);
    });
    expect(hook.result.current.saving).toBe(false);
  });

  it("releases the write guard after a failed card update", async () => {
    mocks.update.mockRejectedValueOnce(new Error("write rejected"));
    const hook = await renderHook(() => useDiscoveryCardDraft(project()));
    await hook.act(async () => hook.result.current.save());
    expect(hook.result.current.saving).toBe(false);
    await hook.act(async () => hook.result.current.save());
    expect(mocks.update).toHaveBeenCalledTimes(2);
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it("loads the new project's fields before allowing its card to be saved", async () => {
    const hook = await renderHook(
      (record: Project = project()) => useDiscoveryCardDraft(record),
      { initialProps: project() },
    );
    await hook.act(() =>
      hook.result.current.setField("summary", "OLD PROJECT EDIT"),
    );
    await hook.rerender(project("project-2", "SECOND PROJECT"));
    expect(hook.result.current.values.summary).toBe("SECOND PROJECT");
    await hook.act(async () => hook.result.current.save());
    expect(mocks.update).toHaveBeenCalledWith(
      "project-2",
      expect.objectContaining({
        discovery_card: expect.objectContaining({ summary: "SECOND PROJECT" }),
      }),
    );
  });

  it("refreshes server facts without discarding fields the reviewer has edited", async () => {
    const hook = await renderHook(
      (record: Project = project()) => useDiscoveryCardDraft(record),
      { initialProps: project() },
    );
    await hook.act(() =>
      hook.result.current.setField("summary", "UNSAVED SUMMARY"),
    );
    await hook.rerender({
      ...project(),
      index_card: { ...project().index_card, highlights: ["Ký túc xá"] },
    });
    expect(hook.result.current.values.summary).toBe("UNSAVED SUMMARY");
    expect(hook.result.current.values.highlights).toBe("Ký túc xá");
  });

  it("ignores a save receipt after the reviewer has changed projects", async () => {
    let complete!: () => void;
    mocks.update.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        }),
    );
    const hook = await renderHook(
      (record: Project = project()) => useDiscoveryCardDraft(record),
      { initialProps: project() },
    );
    let saving!: Promise<void>;
    await hook.act(() => {
      saving = hook.result.current.save();
    });
    await hook.rerender(project("project-2", "SECOND PROJECT"));
    await hook.act(async () => {
      complete();
      await saving;
    });
    expect(mocks.notify).not.toHaveBeenCalled();
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(hook.result.current.saving).toBe(false);
  });
});
