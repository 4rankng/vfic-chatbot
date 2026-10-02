import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";
import type * as RaCoreModule from "ra-core";
import { render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import "./projects.css";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  listExternalSources: vi.fn(),
  listSinglePageExternalSources: vi.fn(),
  runExternalSourceNow: vi.fn(),
  runSinglePageExternalSourceNow: vi.fn(),
  deleteExternalSource: vi.fn(),
  deleteSinglePageExternalSource: vi.fn(),
}));

// The list's empty state comes from `../kit`, whose barrel also exports the
// react-admin bound form controls; those import `useInput` from `ra-core`, so
// the mock spreads the real module instead of narrowing it to one export.
vi.mock("ra-core", async (importOriginal) => ({
  ...(await importOriginal<typeof RaCoreModule>()),
  useNotify: () => mocks.notify,
}));

vi.mock("./project-knowledge-service", async (importOriginal) => ({
  ...(await importOriginal()),
  listExternalSources: mocks.listExternalSources,
  listSinglePageExternalSources: mocks.listSinglePageExternalSources,
  runExternalSourceNow: mocks.runExternalSourceNow,
  runSinglePageExternalSourceNow: mocks.runSinglePageExternalSourceNow,
  deleteExternalSource: mocks.deleteExternalSource,
  deleteSinglePageExternalSource: mocks.deleteSinglePageExternalSource,
}));

import { ExternalSourceList } from "./ExternalSourceList";
import { SINGLE_PAGE_SYNC_MAX_POLL_MS } from "./domain/externalSourcePolling";

let queryClient: QueryClient;

/** The list reads its query from the react-admin QueryClient in the app. */
const QueryClientWrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>
    <div className="inbox-bg-container project-workspace">{children}</div>
  </QueryClientProvider>
);

const renderList = (ui: ReactElement) =>
  render(ui, { wrapper: QueryClientWrapper });

const faqRow = {
  id: "src-1",
  project_id: "project-1",
  category_key: "faq",
  source_kind: "google_sheet",
  sheet_url: "https://docs.google.com/spreadsheets/d/abc/edit",
  sheet_gid: 0,
  auto_sync_enabled: true,
  consecutive_failures: 0,
  last_status: "OK",
  last_synced_at: "2026-07-21T10:00:00Z",
  updated_at: "2026-07-21T10:00:00Z",
};

const singlePageRow = {
  id: "src-sp-1",
  project_id: "project-1",
  source_kind: "google_sheet",
  sheet_url: "https://docs.google.com/spreadsheets/d/abc/edit#gid=987654321",
  sheet_gid: 987654321,
  auto_sync_enabled: false,
  consecutive_failures: 0,
  last_status: "NO_OP",
  last_row_count: 18,
  last_synced_at: "2026-07-21T10:05:00Z",
  updated_at: "2026-07-21T10:05:00Z",
};

describe("ExternalSourceList", () => {
  it("keeps polling through the full worker timeout and retry budget", () => {
    expect(SINGLE_PAGE_SYNC_MAX_POLL_MS).toBe((4 * 1800 + 3 * 2000) * 1000);
  });

  afterEach(async () => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    await page.viewport(1280, 720);
  });

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.listExternalSources.mockResolvedValue([faqRow]);
    mocks.listSinglePageExternalSources.mockResolvedValue([singlePageRow]);
    mocks.runExternalSourceNow.mockResolvedValue({ job_id: "job-1" });
    mocks.runSinglePageExternalSourceNow.mockResolvedValue({
      job_id: "job-sp-1",
    });
    mocks.deleteExternalSource.mockResolvedValue(undefined);
    mocks.deleteSinglePageExternalSource.mockResolvedValue(undefined);
  });

  it("renders the configured source row with its status", async () => {
    const screen = await renderList(
      <ExternalSourceList projectId="project-1" />,
    );
    await vi.waitFor(() =>
      expect(mocks.listExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );
    await expect
      .element(screen.getByRole("button", { name: "Đồng bộ ngay" }))
      .toBeVisible();
    await expect
      .element(screen.getByLabelText("Tự động mỗi ngày"))
      .toBeVisible();
    await expect.element(screen.getByText("24h")).toBeVisible();
    expect(screen.container.textContent).not.toContain("Tự động mỗi ngày");
    expect(screen.container.textContent).not.toContain("Đồng bộ gần nhất:");
  });

  it("separates source identity, sync state, and actions on wide screens", async () => {
    await page.viewport(1200, 720);

    const screen = await renderList(
      <ExternalSourceList projectId="project-1" />,
    );
    await vi.waitFor(() =>
      expect(mocks.listExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );
    await vi.waitFor(() =>
      expect(
        screen.container.querySelector(".project-external-source-row"),
      ).not.toBeNull(),
    );

    const row = screen.container.querySelector(".project-external-source-row")!;
    const identity = row
      .querySelector(".project-external-source-identity")!
      .getBoundingClientRect();
    const sync = row
      .querySelector(".project-external-source-sync")!
      .getBoundingClientRect();
    const actions = row
      .querySelector(".project-external-source-actions")!
      .getBoundingClientRect();

    expect(identity.right).toBeLessThanOrEqual(sync.left + 0.5);
    expect(sync.right).toBeLessThanOrEqual(actions.left + 0.5);
  });

  it("stacks the row before tablet-width actions can overflow", async () => {
    await page.viewport(768, 900);

    const screen = await renderList(
      <ExternalSourceList projectId="project-1" />,
    );
    await vi.waitFor(() =>
      expect(mocks.listExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );
    await vi.waitFor(() =>
      expect(
        screen.container.querySelector(".project-external-source-row"),
      ).not.toBeNull(),
    );

    const row = screen.container.querySelector(".project-external-source-row")!;
    const identity = row
      .querySelector(".project-external-source-identity")!
      .getBoundingClientRect();
    const sync = row
      .querySelector(".project-external-source-sync")!
      .getBoundingClientRect();
    const actions = row
      .querySelector(".project-external-source-actions")!
      .getBoundingClientRect();
    const rowRect = row.getBoundingClientRect();

    expect(sync.top).toBeGreaterThanOrEqual(identity.bottom - 0.5);
    expect(actions.top).toBeGreaterThanOrEqual(sync.bottom - 0.5);
    expect(actions.right).toBeLessThanOrEqual(rowRect.right + 0.5);
  });

  it("triggers run-now from the sync action", async () => {
    const screen = await renderList(
      <ExternalSourceList projectId="project-1" />,
    );
    await screen.getByRole("button", { name: "Đồng bộ ngay" }).click();

    await vi.waitFor(() =>
      expect(mocks.runExternalSourceNow).toHaveBeenCalledWith(
        "project-1",
        "src-1",
      ),
    );
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.stringContaining("Đang xử lý"),
      { type: "info" },
    );
  });

  it("keeps polling an already-synced manual run across an immediate refresh", async () => {
    const onSynchronized = vi.fn();
    mocks.listSinglePageExternalSources
      .mockResolvedValueOnce([singlePageRow])
      .mockResolvedValueOnce([singlePageRow])
      .mockResolvedValueOnce([
        {
          ...singlePageRow,
          last_status: "OK",
          last_content_hash: "new-hash",
          last_synced_at: "2026-07-21T10:06:00Z",
          updated_at: "2026-07-21T10:06:00Z",
        },
      ]);
    const screen = await renderList(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={0}
        onSynchronized={onSynchronized}
      />,
    );
    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(1),
    );

    vi.useFakeTimers();
    await screen.getByRole("button", { name: "Đồng bộ ngay" }).click();
    await screen.rerender(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={1}
        onSynchronized={onSynchronized}
      />,
    );
    await vi.advanceTimersByTimeAsync(4000);

    expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(3);
    await vi.waitFor(() => expect(onSynchronized).toHaveBeenCalledTimes(1));
  });

  it("polls a slow create until a changed terminal row appears", async () => {
    const onSynchronized = vi.fn();
    const pendingRow = { ...singlePageRow, last_status: "NEW" };
    const completedRow = {
      ...singlePageRow,
      last_status: "OK",
      last_content_hash: "created-hash",
      last_synced_at: "2026-07-21T10:08:00Z",
      updated_at: "2026-07-21T10:08:00Z",
    };
    mocks.listSinglePageExternalSources
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([pendingRow])
      .mockResolvedValueOnce([pendingRow])
      .mockResolvedValueOnce([completedRow]);
    const screen = await renderList(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={0}
        onSynchronized={onSynchronized}
      />,
    );
    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(1),
    );

    vi.useFakeTimers();
    await screen.rerender(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={1}
        onSynchronized={onSynchronized}
      />,
    );
    await vi.advanceTimersByTimeAsync(16_000);

    expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(6);
    await vi.waitFor(() => expect(onSynchronized).toHaveBeenCalledTimes(1));
  });

  it("stops polling a hidden tab and resumes when it is visible again", async () => {
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("visible");
    mocks.listSinglePageExternalSources
      .mockResolvedValueOnce([singlePageRow])
      .mockResolvedValue([{ ...singlePageRow, last_status: "PROCESSING" }]);

    const screen = await renderList(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={0}
      />,
    );
    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(1),
    );

    vi.useFakeTimers();
    await screen.rerender(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={1}
      />,
    );
    await vi.advanceTimersByTimeAsync(4000);
    expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(3);

    visibility.mockReturnValue("hidden");
    window.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(3);

    visibility.mockReturnValue("visible");
    window.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(4000);
    expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(4);
  });

  it("ignores an older list response after a newer request wins", async () => {
    let resolveOlder!: (rows: (typeof singlePageRow)[]) => void;
    const older = new Promise<(typeof singlePageRow)[]>((resolve) => {
      resolveOlder = resolve;
    });
    const newerRow = { ...singlePageRow, last_row_count: 44 };
    const onSynchronized = vi.fn();
    mocks.listSinglePageExternalSources
      .mockReturnValueOnce(older)
      .mockResolvedValueOnce([newerRow]);

    const screen = await renderList(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={0}
        onSynchronized={onSynchronized}
      />,
    );
    await screen.rerender(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={1}
        onSynchronized={onSynchronized}
      />,
    );
    await expect.element(screen.getByLabelText("44 hàng")).toBeVisible();

    resolveOlder([singlePageRow]);
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    await expect.element(screen.getByLabelText("44 hàng")).toBeVisible();
    expect(screen.container.textContent).not.toContain("18 hàng");
    expect(onSynchronized).not.toHaveBeenCalled();
  });

  it("renders recovery copy instead of a backend error code", async () => {
    mocks.listSinglePageExternalSources.mockResolvedValue([
      {
        ...singlePageRow,
        last_status: "FAILED",
        last_error: "sheet_not_public",
      },
    ]);
    const screen = await renderList(
      <ExternalSourceList projectId="project-1" variant="single-page" />,
    );

    await expect
      .element(screen.getByText(/Google Sheet chưa công khai/))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("sheet_not_public");
  });

  it("stacks source details and actions inside a phone-width row", async () => {
    await page.viewport(320, 844);

    const screen = await renderList(
      <ExternalSourceList projectId="project-1" />,
    );
    await vi.waitFor(() =>
      expect(mocks.listExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );

    const runButton = screen.getByRole("button", { name: "Đồng bộ ngay" });
    await expect.element(runButton).toBeVisible();

    const row = runButton
      .element()
      .closest<HTMLElement>(".project-external-source-row")!;
    const actions = runButton.element().parentElement!;
    const identity = row
      .querySelector(".project-external-source-identity")!
      .getBoundingClientRect();
    const sync = row
      .querySelector(".project-external-source-sync")!
      .getBoundingClientRect();
    const rowRect = row.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();

    expect(sync.top).toBeGreaterThanOrEqual(identity.bottom - 0.5);
    expect(actionsRect.top).toBeGreaterThanOrEqual(sync.bottom - 0.5);
    expect(actionsRect.left).toBeGreaterThanOrEqual(rowRect.left - 0.5);
    expect(actionsRect.right).toBeLessThanOrEqual(rowRect.right + 0.5);
    expect(actions.clientWidth).toBeLessThanOrEqual(row.clientWidth);
  });

  it("renders single-page sync details and refreshes from the single-page endpoint", async () => {
    const screen = await renderList(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={0}
      />,
    );
    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );

    await expect.element(screen.getByText("gid=987654321")).toBeVisible();
    await expect.element(screen.getByLabelText("18 hàng")).toBeVisible();

    // The parent (SinglePagePanel) bumps refreshSignal after a source change to
    // re-trigger load() — that is now the primary refresh path on this page.
    await screen.rerender(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        refreshSignal={1}
      />,
    );

    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(2),
    );
  });

  it("confirms and deletes a single-page source with the dedicated endpoint", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const screen = await renderList(
      <ExternalSourceList projectId="project-1" variant="single-page" />,
    );

    await screen.getByRole("button", { name: "Xóa nguồn đồng bộ" }).click();

    await vi.waitFor(() =>
      expect(mocks.deleteSinglePageExternalSource).toHaveBeenCalledWith(
        "project-1",
        "src-sp-1",
      ),
    );
    expect(confirmSpy).toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("hides mutation controls in single-page read-only mode", async () => {
    const screen = await renderList(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        mutable={false}
      />,
    );
    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );

    expect(
      screen.container.querySelector(".project-external-source-actions"),
    ).toBeNull();
    expect(screen.container.textContent).not.toContain("Xóa nguồn đồng bộ");
  });

  it("offers retry instead of an empty source state when loading fails", async () => {
    mocks.listSinglePageExternalSources.mockRejectedValueOnce(
      new Error("Service unavailable"),
    );
    const screen = await renderList(
      <ExternalSourceList projectId="project-1" variant="single-page" />,
    );
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Chưa tải được nguồn đồng bộ");
    expect(screen.container.textContent).not.toContain("Chưa có nguồn đồng bộ");
    await screen.getByRole("button", { name: "Thử lại" }).click();
    await expect.element(screen.getByLabelText("18 hàng")).toBeVisible();
  });

  it("locks source actions during deletion and drops its result after navigation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let finish!: () => void;
    mocks.deleteSinglePageExternalSource.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const onChange = vi.fn();
    const screen = await renderList(
      <ExternalSourceList
        projectId="project-1"
        variant="single-page"
        onChange={onChange}
      />,
    );
    await screen.getByRole("button", { name: "Xóa nguồn đồng bộ" }).click();
    await expect
      .element(screen.getByRole("button", { name: "Đồng bộ ngay" }))
      .toBeDisabled();
    await expect
      .element(screen.getByRole("button", { name: "Xóa nguồn đồng bộ" }))
      .toBeDisabled();
    await screen.rerender(
      <ExternalSourceList
        projectId="project-2"
        variant="single-page"
        onChange={onChange}
      />,
    );
    await expect
      .element(screen.getByRole("button", { name: "Đồng bộ ngay" }))
      .toBeEnabled();
    finish();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(mocks.notify).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not start a cooldown in another project when an old run completes", async () => {
    let finish!: (value: { job_id: string }) => void;
    mocks.runSinglePageExternalSourceNow.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const screen = await renderList(
      <ExternalSourceList projectId="project-1" variant="single-page" />,
    );
    await screen.getByRole("button", { name: "Đồng bộ ngay" }).click();
    await screen.rerender(
      <ExternalSourceList projectId="project-2" variant="single-page" />,
    );
    await expect
      .element(screen.getByRole("button", { name: "Đồng bộ ngay" }))
      .toBeEnabled();
    finish({ job_id: "old-job" });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await expect
      .element(screen.getByRole("button", { name: "Đồng bộ ngay" }))
      .toBeEnabled();
    expect(mocks.notify).not.toHaveBeenCalled();
  });
});
