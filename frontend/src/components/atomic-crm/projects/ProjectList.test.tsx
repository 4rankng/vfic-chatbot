import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";
import type { Project } from "../types";

vi.mock("./ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: ({ project }: { project: Project }) => (
    <div data-testid={`knowledge-${project.id}`}>
      {project.knowledge_mode === "DIRECT_CONTEXT"
        ? "Kiến thức một trang"
        : "Kiến thức theo danh mục"}
    </div>
  ),
}));

import { ProjectAccordionList } from "./ProjectList";

const projects: Project[] = [
  {
    id: "rag-project",
    name: "LG Display",
    slug: "lg-display",
    is_active: true,
    knowledge_mode: "RAG",
    knowledge_document_count: 6,
    feature_readiness: { ready: 12, total: 12 },
    default_persona_id: "persona-1",
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  },
  {
    id: "single-project",
    name: "Dự án một trang",
    slug: "du-an-mot-trang",
    is_active: false,
    knowledge_mode: "DIRECT_CONTEXT",
    knowledge_document_count: 1,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  },
];

describe("ProjectAccordionList", () => {
  it("expands one project KB at a time and lets the open project collapse", async () => {
    const screen = await render(
      <ProjectAccordionList
        projects={projects}
        isAdmin={false}
        canEdit={false}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    const ragTrigger = screen.getByRole("button", {
      name: "Mở hoặc đóng kiến thức dự án LG Display",
    });
    const singleTrigger = screen.getByRole("button", {
      name: "Mở hoặc đóng kiến thức dự án Dự án một trang",
    });

    await expect.element(ragTrigger).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.container.querySelector('[data-testid="knowledge-rag-project"]'),
    ).toBeNull();

    await ragTrigger.click();
    await expect.element(ragTrigger).toHaveAttribute("aria-expanded", "true");
    await expect
      .element(screen.getByTestId("knowledge-rag-project"))
      .toBeVisible();

    await singleTrigger.click();
    await expect.element(ragTrigger).toHaveAttribute("aria-expanded", "false");
    await expect
      .element(singleTrigger)
      .toHaveAttribute("aria-expanded", "true");
    await expect
      .element(screen.getByTestId("knowledge-single-project"))
      .toBeVisible();

    await singleTrigger.click();
    await expect
      .element(singleTrigger)
      .toHaveAttribute("aria-expanded", "false");
    expect(
      screen.container.querySelector(
        '[data-testid="knowledge-single-project"]',
      ),
    ).toBeNull();
  });
});
