import { useState } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@/index.css";
import "@/flat-surfaces.css";
import "../conversations/inbox.css";
import "./projects.css";
import { ProjectDirectoryFilters, ProjectAccordionList } from "./ProjectList";
import { IngestProgressBoard } from "./presentation/IngestProgressBoard";
import { ProjectBriefImport } from "./presentation/ProjectBriefImport";
import type { Project } from "../types";

vi.mock("./ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: () => <div>Kiến thức dự án</div>,
}));
const longName =
  "Dự án tuyển dụng công nhân sản xuất linh kiện điện tử tại Hải Phòng — " +
  "TênDựÁnRấtDài".repeat(8);
const project: Project = {
  id: "project-1",
  name: longName,
  slug: "du-an-" + "dien-tu-".repeat(40),
  is_active: true,
  knowledge_mode: "RAG",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};
const Workspace = () => {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  return (
    <div id="root" className="workspace-frame-content">
      <div className="inbox-bg-container project-workspace">
        <div className="app project-app">
          <section className="panel center-panel project-center-panel">
            <div className="project-workspace-content">
              <div className="project-page-shell">
                <ProjectDirectoryFilters
                  query={query}
                  status={status}
                  onQueryChange={setQuery}
                  onStatusChange={setStatus}
                  onClear={() => {
                    setQuery("");
                    setStatus("all");
                  }}
                />
                <ProjectAccordionList
                  projects={[project]}
                  isAdmin={false}
                  canEdit={false}
                  onEdit={() => undefined}
                  onDeleted={() => undefined}
                />
                <ProjectBriefImport
                  brief={null}
                  filename=""
                  onImported={() => undefined}
                />
                <IngestProgressBoard
                  slow
                  items={[
                    { key: "compensation", status: "processing" },
                    { key: "requirements", status: "active" },
                  ]}
                />
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

describe("recruitment project workspace across device sizes", () => {
  it.each([320, 360, 390, 768, 1440])(
    "keeps long project content, filters and training progress usable at %ipx",
    async (width) => {
      await page.viewport(width, 900);
      const screen = await render(<Workspace />);
      const shell = screen.container.querySelector<HTMLElement>(
        ".project-page-shell",
      )!;
      expect(shell.scrollWidth).toBeLessThanOrEqual(shell.clientWidth + 1);
      expect(document.scrollingElement!.scrollWidth).toBeLessThanOrEqual(
        width + 1,
      );
      const search = screen.getByRole("searchbox", { name: "Tìm dự án" });
      await expect.element(search).toBeVisible();
      expect(
        getComputedStyle(search.element().parentElement!).borderWidth,
      ).toBe("1px");
      expect(getComputedStyle(search.element().parentElement!).boxShadow).toBe(
        "none",
      );
      await search.fill("Hải Phòng");
      await expect
        .element(screen.getByRole("button", { name: "Xóa bộ lọc" }))
        .toBeVisible();
      await screen.getByRole("button", { name: "Xóa bộ lọc" }).click();
      await expect.element(search).toHaveValue("");
      if (width < 768) {
        const upload = screen
          .getByRole("button", { name: "Nhập từ tệp" })
          .element();
        expect(upload.getBoundingClientRect().height).toBe(40);
      }
      const filters = screen.container.querySelector<HTMLElement>(
        ".project-directory-filters",
      )!;
      expect(
        getComputedStyle(filters).gridTemplateColumns.split(" ").length,
      ).toBe(width < 768 ? 1 : 3);
      expect(getComputedStyle(filters).gap).toBe("12px");
      expect(getComputedStyle(filters).padding).toBe("16px");
      const expectedHeight = width < 768 ? 40 : 36;
      const inputBox = search.element().parentElement!;
      expect(inputBox.getBoundingClientRect().height).toBe(expectedHeight);
      const statusControl = screen
        .getByRole("button", { name: /Trạng thái tuyển dụng/ })
        .element();
      expect(statusControl.getBoundingClientRect().height).toBe(expectedHeight);
      const touch = window.matchMedia("(pointer: coarse)").matches;
      expect(getComputedStyle(search.element()).fontSize).toBe(
        touch ? "16px" : "12px",
      );
      const statusLabel = statusControl.querySelector("p")!;
      expect(getComputedStyle(statusLabel).fontSize).toBe("12px");
    },
  );

  it("offers active/inactive project filters with an accessible control", async () => {
    const screen = await render(<Workspace />);
    await screen.getByRole("button", { name: /Trạng thái tuyển dụng/ }).click();
    expect(
      screen.getByRole("listbox").element().closest(".uu-scope"),
    ).not.toBeNull();
    await screen.getByRole("option", { name: "Đang tuyển dụng" }).click();
    await expect
      .element(screen.getByRole("button", { name: /Trạng thái tuyển dụng/ }))
      .toHaveTextContent("Đang tuyển dụng");
  });
});
