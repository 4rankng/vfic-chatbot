import { useState } from "react";
import { render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeSource } from "../types";
import "../conversations/inbox.css";

vi.mock("./KnowledgeSourceRow", () => ({
  KnowledgeSourceRow: ({
    source,
    selected,
    onSelect,
  }: {
    source: KnowledgeSource;
    selected: boolean;
    onSelect: () => void;
  }) => (
    <button
      type="button"
      aria-pressed={selected}
      aria-controls="knowledge-source-detail"
      onClick={onSelect}
    >
      {source.file_name}
    </button>
  ),
}));

vi.mock("./KnowledgeDetailPanel", () => ({
  KnowledgeDetailPanel: ({
    source,
    headingId,
  }: {
    source: KnowledgeSource;
    headingId?: string;
  }) => <h3 id={headingId}>Chi tiết: {source.file_name}</h3>,
}));

vi.mock("@/components/admin/list-pagination", () => ({
  ListPagination: () => <div>Phân trang</div>,
}));

import { KnowledgeSourceWorkspace } from "./KnowledgeSourceList";

const sources: KnowledgeSource[] = [
  {
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
  },
  {
    id: "source-b",
    drive_file_id: null,
    file_name: "Phúc lợi ca kíp.md",
    source: "upload",
    version: "1",
    status: "PUBLISHED",
    stage: "PUBLISHED",
    project_id: "project-b",
    project_name: "Rorze",
    mime_type: "text/markdown",
    digest_meta: { unit_count: 5 },
    created_at: "2026-07-22T00:00:00Z",
    updated_at: "2026-07-23T00:00:00Z",
  },
];

const WorkspaceHarness = () => {
  const [selectedId, setSelectedId] = useState("source-a");
  return (
    <KnowledgeSourceWorkspace
      sources={sources}
      selectedSource={
        sources.find((source) => source.id === selectedId) ?? null
      }
      total={sources.length}
      onSelect={setSelectedId}
    />
  );
};

describe("KnowledgeSourceWorkspace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the clicked source in the detail region", async () => {
    const screen = await render(<WorkspaceHarness />);

    await expect
      .element(screen.getByText("Chi tiết: Chính sách tuyển dụng.md"))
      .toBeVisible();

    await screen.getByRole("button", { name: "Phúc lợi ca kíp.md" }).click();

    await expect
      .element(screen.getByText("Chi tiết: Phúc lợi ca kíp.md"))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Phúc lợi ca kíp.md" }))
      .toHaveAttribute("aria-pressed", "true");
  });

  it("moves focus to the selected detail on a phone", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query) =>
        ({
          matches: query === "(max-width: 760px)",
          media: query,
          onchange: null,
          addListener: vi.fn(),
          removeListener: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          dispatchEvent: vi.fn(() => true),
        }) as MediaQueryList,
    );
    const scrollIntoView = vi
      .spyOn(HTMLElement.prototype, "scrollIntoView")
      .mockImplementation(() => undefined);
    const screen = await render(<WorkspaceHarness />);

    await screen.getByRole("button", { name: "Phúc lợi ca kíp.md" }).click();

    await vi.waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalledWith({
        behavior: "smooth",
        block: "start",
      });
    });
    expect(document.activeElement).toBe(
      screen.container.querySelector("#knowledge-source-detail"),
    );
  });

  it("stacks the detail below navigation in the phone viewport", async () => {
    const screen = await render(<WorkspaceHarness />);
    const workspace = screen.container.querySelector(
      ".knowledge-source-workspace",
    );
    const navigation = screen.container.querySelector(
      ".knowledge-source-navigation",
    );
    const detail = screen.container.querySelector("#knowledge-source-detail");

    expect(workspace).toBeInstanceOf(HTMLElement);
    expect(navigation).toBeInstanceOf(HTMLElement);
    expect(detail).toBeInstanceOf(HTMLElement);
    expect(window.getComputedStyle(workspace as HTMLElement).display).toBe(
      "block",
    );

    const navigationBounds = (
      navigation as HTMLElement
    ).getBoundingClientRect();
    const detailBounds = (detail as HTMLElement).getBoundingClientRect();
    expect(detailBounds.top).toBeGreaterThanOrEqual(navigationBounds.bottom);
    expect(detailBounds.left).toBe(navigationBounds.left);
  });
});
