// Visibility-gating tests for the knowledge list's 5s pipeline auto-refresh.
//
// The interval only runs while a source is moving through the pipeline, and a
// hidden tab must not keep hitting the backend: the interval is disarmed while
// the document is hidden and re-arms when it becomes visible again.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook } from "vitest-browser-react";

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock("ra-core", () => ({
  useRefresh: () => mocks.refresh,
}));

import { usePipelineAutoRefresh } from "./usePipelineAutoRefresh";
import type { KnowledgeSource } from "../types";

const source = (stage: string): KnowledgeSource => ({
  id: "src-1",
  drive_file_id: null,
  file_name: "huong-dan.pdf",
  source: "upload",
  version: null,
  status: stage,
  created_at: "2026-09-27T00:00:00Z",
  updated_at: `2026-09-27T00:00:0${2}Z`,
  stage,
});

const activeSource = () => source("DIGESTING");
const publishedSource = () => source("PUBLISHED");

describe("usePipelineAutoRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.refresh.mockReset();
  });

  afterEach(async () => {
    await cleanup();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("refreshes every 5s while a source is in the pipeline and the tab is visible", async () => {
    const hook = await renderHook(
      (props: { sources: KnowledgeSource[] }) =>
        usePipelineAutoRefresh(props.sources),
      { initialProps: { sources: [activeSource()] } },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(2);
  });

  it("does not poll when no source is moving through the pipeline", async () => {
    const hook = await renderHook(
      (props: { sources: KnowledgeSource[] }) =>
        usePipelineAutoRefresh(props.sources),
      { initialProps: { sources: [publishedSource()] } },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it("stops polling a hidden tab and resumes when it is visible again", async () => {
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("visible");
    const hook = await renderHook(
      (props: { sources: KnowledgeSource[] }) =>
        usePipelineAutoRefresh(props.sources),
      { initialProps: { sources: [activeSource()] } },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);

    visibility.mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    // The interval is disarmed while nothing is watching.
    expect(mocks.refresh).toHaveBeenCalledTimes(1);

    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(2);
  });

  it("does not arm the interval while the tab is hidden on mount", async () => {
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("hidden");
    const hook = await renderHook(
      (props: { sources: KnowledgeSource[] }) =>
        usePipelineAutoRefresh(props.sources),
      { initialProps: { sources: [activeSource()] } },
    );
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(11_000);
    });
    expect(mocks.refresh).not.toHaveBeenCalled();

    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await hook.act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });
});
