import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";
import type { Project } from "../types";
import { ProjectOperationsPanel } from "./ProjectSidebar";

const project: Project = {
  id: "project-1",
  name: "LG Display",
  slug: "lg-display",
  is_active: true,
  knowledge_mode: "RAG",
  knowledge_document_count: 4,
  feature_readiness: { ready: 9, total: 12 },
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
};

describe("ProjectOperationsPanel", () => {
  it("shows only document and readiness facts in the selected project summary", async () => {
    const screen = await render(
      <ProjectOperationsPanel
        projects={[project]}
        selectedId={project.id}
        selectedProject={project}
        isPending={false}
        isAdmin={false}
        canEdit={false}
        onSelect={vi.fn()}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    await expect.element(screen.getByText("LG Display")).toBeVisible();
    await expect.element(screen.getByText("4")).toBeVisible();
    await expect.element(screen.getByText("9/12")).toBeVisible();
    expect(screen.container.textContent).not.toContain("Agent");
  });
});
