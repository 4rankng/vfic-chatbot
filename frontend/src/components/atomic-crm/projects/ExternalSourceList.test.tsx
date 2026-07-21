import { render } from "vitest-browser-react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  listExternalSources: vi.fn(),
  runExternalSourceNow: vi.fn(),
  deleteExternalSource: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("@/lib/vfic/knowledgeService", () => ({
  listExternalSources: mocks.listExternalSources,
  runExternalSourceNow: mocks.runExternalSourceNow,
  deleteExternalSource: mocks.deleteExternalSource,
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
};

describe("ExternalSourceList", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.listExternalSources.mockResolvedValue([faqRow]);
    mocks.runExternalSourceNow.mockResolvedValue({ job_id: "job-1" });
    mocks.deleteExternalSource.mockResolvedValue(undefined);
  });

  it("renders the configured source row with its status", async () => {
    const screen = await render(<ExternalSourceList projectId="project-1" />);
    await vi.waitFor(() =>
      expect(mocks.listExternalSources).toHaveBeenCalledWith("project-1"),
    );
    await expect
      .element(screen.getByRole("button", { name: "Xử lý ngay" }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Tự động mỗi ngày"))
      .toBeVisible();
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
});
