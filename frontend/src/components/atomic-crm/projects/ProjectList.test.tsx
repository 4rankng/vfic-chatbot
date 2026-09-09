import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";
import type { Project } from "../types";

vi.mock("./ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: ({
    project,
    editable,
    canManageSources,
  }: {
    project: Project;
    editable?: boolean;
    canManageSources?: boolean;
  }) => (
    <div
      data-testid={`knowledge-${project.id}`}
      data-editable={String(Boolean(editable))}
      data-can-manage-sources={String(Boolean(canManageSources))}
    >
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
    feature_readiness: { ready: 0, total: 12 },
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  },
];

describe("ProjectAccordionList", () => {
  it("shows one-page readiness without applying the RAG feature score", async () => {
    const screen = await render(
      <ProjectAccordionList
        projects={[projects[1]]}
        isAdmin={false}
        canEdit={false}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    await expect.element(screen.getByText("Đã sẵn sàng")).toBeVisible();
    expect(screen.container.textContent).not.toContain("0/12");
  });

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
    expect(screen.container.textContent).not.toContain("Agent");

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

  it("lets recruiters edit text without exposing admin source management", async () => {
    const screen = await render(
      <ProjectAccordionList
        projects={[projects[0]]}
        isAdmin={false}
        canEdit
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    await screen
      .getByRole("button", {
        name: "Mở hoặc đóng kiến thức dự án LG Display",
      })
      .click();

    const knowledgePanel = screen.getByTestId("knowledge-rag-project");
    await expect
      .element(knowledgePanel)
      .toHaveAttribute("data-editable", "true");
    await expect
      .element(knowledgePanel)
      .toHaveAttribute("data-can-manage-sources", "false");
  });

  it("toggles a project on and off without deleting it", async () => {
    const onToggleActive = vi.fn();
    const screen = await render(
      <ProjectAccordionList
        projects={projects}
        isAdmin={false}
        canEdit
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
        onToggleActive={onToggleActive}
      />,
    );

    // The active project offers to turn itself off...
    await screen
      .getByRole("button", {
        name: "Mở hoặc đóng kiến thức dự án LG Display",
      })
      .click();
    const disableButton = screen.getByRole("button", {
      name: "Tắt dự án LG Display",
    });
    await expect.element(disableButton).toBeVisible();
    await disableButton.click();
    expect(onToggleActive).toHaveBeenCalledWith(projects[0]);

    // ...and the inactive one offers the reverse.
    await screen
      .getByRole("button", {
        name: "Mở hoặc đóng kiến thức dự án Dự án một trang",
      })
      .click();
    await expect
      .element(screen.getByRole("button", { name: "Bật dự án Dự án một trang" }))
      .toBeVisible();
  });

  it("hides the toggle when no handler is supplied", async () => {
    const screen = await render(
      <ProjectAccordionList
        projects={[projects[0]]}
        isAdmin={false}
        canEdit
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    await screen
      .getByRole("button", {
        name: "Mở hoặc đóng kiến thức dự án LG Display",
      })
      .click();
    expect(
      screen.container.querySelector('[aria-label="Tắt dự án LG Display"]'),
    ).toBeNull();
  });
});
