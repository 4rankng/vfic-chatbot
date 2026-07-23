import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

import type { KnowledgeSource } from "../types";
import "../conversations/inbox.css";

const mocks = vi.hoisted(() => ({
  redirect: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useRedirect: () => mocks.redirect,
  useRefresh: () => mocks.refresh,
}));

vi.mock("@/components/admin", () => ({
  DeleteButton: () => <button type="button">Xóa</button>,
}));

import { KnowledgeSourceRow } from "./KnowledgeSourceRow";

const source: KnowledgeSource = {
  id: "source-a",
  drive_file_id: null,
  file_name: "Chính sách tuyển dụng.md",
  source: "upload",
  version: "1",
  status: "PUBLISHED",
  stage: "PUBLISHED",
  project_id: "project-a",
  project_name: "LG Display",
  mime_type: "text/markdown",
  digest_meta: { unit_count: 8 },
  created_at: "2026-07-22T00:00:00Z",
  updated_at: "2026-07-23T00:00:00Z",
};

describe("KnowledgeSourceRow", () => {
  it("uses a direct, accessible selection button with a comfortable target", async () => {
    const onSelect = vi.fn();
    const screen = await render(
      <div role="list">
        <KnowledgeSourceRow
          source={source}
          selected
          onSelect={onSelect}
        />
      </div>,
    );

    const select = screen.getByRole("button", {
      name: "Xem Chính sách tuyển dụng.md",
    });
    await expect.element(select).toHaveAttribute("aria-pressed", "true");
    await expect
      .element(select)
      .toHaveAttribute("aria-controls", "knowledge-source-detail");
    await expect.element(screen.getByText("LG Display", { exact: false })).toBeVisible();

    expect(select.element().getBoundingClientRect().height).toBeGreaterThanOrEqual(
      44,
    );
    await select.click();
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});

