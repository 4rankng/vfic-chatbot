import { render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "@/index.css";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  listExternalSources: vi.fn(),
  listSinglePageExternalSources: vi.fn(),
  runExternalSourceNow: vi.fn(),
  runSinglePageExternalSourceNow: vi.fn(),
  deleteExternalSource: vi.fn(),
  deleteSinglePageExternalSource: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("@/lib/vfic/knowledgeService", async (importOriginal) => ({
  ...(await importOriginal()),
  listExternalSources: mocks.listExternalSources,
  listSinglePageExternalSources: mocks.listSinglePageExternalSources,
  runExternalSourceNow: mocks.runExternalSourceNow,
  runSinglePageExternalSourceNow: mocks.runSinglePageExternalSourceNow,
  deleteExternalSource: mocks.deleteExternalSource,
  deleteSinglePageExternalSource: mocks.deleteSinglePageExternalSource,
}));

import { ExternalSourceList } from "./ExternalSourceList";

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
  afterEach(async () => {
    vi.useRealTimers();
    await page.viewport(1280, 720);
  });

  beforeEach(() => {
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
    const screen = await render(<ExternalSourceList projectId="project-1" />);
    await vi.waitFor(() =>
      expect(mocks.listExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );
    await expect
      .element(screen.getByRole("button", { name: "Xử lý ngay" }))
      .toBeVisible();
    await expect.element(screen.getByText("Tự động mỗi ngày")).toBeVisible();
  });

  it("triggers run-now on Process now", async () => {
    const screen = await render(<ExternalSourceList projectId="project-1" />);
    await screen.getByRole("button", { name: "Xử lý ngay" }).click();

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
    const screen = await render(
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
    await screen.getByRole("button", { name: "Xử lý ngay" }).click();
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
    expect(onSynchronized).toHaveBeenCalledTimes(1);
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
    const screen = await render(
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
    expect(onSynchronized).toHaveBeenCalledTimes(1);
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

    const screen = await render(
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
    await expect.element(screen.getByText(/44 hàng/)).toBeVisible();

    resolveOlder([singlePageRow]);
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    await expect.element(screen.getByText(/44 hàng/)).toBeVisible();
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
    const screen = await render(
      <ExternalSourceList projectId="project-1" variant="single-page" />,
    );

    await expect
      .element(screen.getByText(/Google Sheet chưa công khai/))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("sheet_not_public");
  });

  it("keeps source details and actions inside a phone-width card", async () => {
    await page.viewport(320, 844);

    const screen = await render(<ExternalSourceList projectId="project-1" />);
    await vi.waitFor(() =>
      expect(mocks.listExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );

    const runButton = screen.getByRole("button", { name: "Xử lý ngay" });
    await expect.element(runButton).toBeVisible();

    const card = runButton
      .element()
      .closest<HTMLElement>(".project-external-source-row")!;
    const actions = runButton.element().parentElement!;
    const cardRect = card.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();

    expect(actionsRect.left).toBeGreaterThanOrEqual(cardRect.left - 0.5);
    expect(actionsRect.right).toBeLessThanOrEqual(cardRect.right + 0.5);
    expect(actions.clientWidth).toBeLessThanOrEqual(card.clientWidth);
  });

  it("renders single-page sync details and refreshes from the single-page endpoint", async () => {
    const screen = await render(
      <ExternalSourceList projectId="project-1" variant="single-page" />,
    );
    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledWith(
        "project-1",
        expect.any(AbortSignal),
      ),
    );

    await expect.element(screen.getByText("gid=987654321")).toBeVisible();
    await expect.element(screen.getByText(/18 hàng/)).toBeVisible();

    await screen.getByRole("button", { name: "Làm mới" }).click();

    await vi.waitFor(() =>
      expect(mocks.listSinglePageExternalSources).toHaveBeenCalledTimes(2),
    );
  });

  it("confirms and deletes a single-page source with the dedicated endpoint", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const screen = await render(
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
    const screen = await render(
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

    expect(screen.container.textContent).not.toContain("Xử lý ngay");
    expect(screen.container.textContent).not.toContain("Xóa nguồn đồng bộ");
  });
});
