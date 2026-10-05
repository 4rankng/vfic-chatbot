import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { Project } from "../types";

vi.mock("./ProjectKnowledgePanel", () => ({
  ProjectKnowledgePanel: ({
    project,
    editable,
    canManageSources,
    toolbar,
  }: {
    project: Project;
    editable?: boolean;
    canManageSources?: boolean;
    toolbar?: ReactNode;
  }) => (
    <div
      data-testid={`knowledge-${project.id}`}
      data-editable={String(Boolean(editable))}
      data-can-manage-sources={String(Boolean(canManageSources))}
    >
      {toolbar}
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
    ingest_state: "ready",
    knowledge_mode: "RAG",
    knowledge_document_count: 6,
    category_readiness: { ready: 12, total: 12 },
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
    category_readiness: { ready: 0, total: 12 },
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  },
];

// Every card leads its badge group with the availability badge (Đang bật /
// Đã tắt); the ingest badge follows when the payload carries ingest_state,
// and the knowledge-mode badge closes the group.
const badgeLabels = (container: HTMLElement): string[][] =>
  Array.from(container.querySelectorAll(".project-accordion-badges")).map(
    (badges) =>
      Array.from(badges.children).map(
        (badge) => badge.textContent?.trim() ?? "",
      ),
  );

describe("ProjectAccordionList", () => {
  it("labels each project's availability from is_active, ingest state beside it", async () => {
    const screen = await render(
      <ProjectAccordionList
        projects={projects}
        isAdmin={false}
        canEdit={false}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    // rag-project is active with ready ingest; single-project is inactive
    // and ships no ingest_state, so it carries no ingest badge at all.
    expect(badgeLabels(screen.container)).toEqual([
      ["Đang bật", "Đã nạp", "Theo danh mục"],
      ["Đã tắt", "Một trang"],
    ]);
    await expect.element(screen.getByText("Đã tắt")).toBeVisible();
    // The retired conflated labels must not resurface anywhere in the list.
    expect(screen.container.textContent).not.toContain("Đang hoạt động");
    expect(screen.container.textContent).not.toContain("Bản nháp");
    expect(screen.container.textContent).not.toContain("Đang tuyển dụng");
  });

  it("maps every ingest_state to its ruled label, independent of availability", async () => {
    const screen = await render(
      <ProjectAccordionList
        projects={[
          {
            ...projects[0],
            id: "ingesting-project",
            name: "LG Display",
            slug: "lg-display",
            ingest_state: "ingesting",
            is_active: true,
          },
          {
            ...projects[0],
            id: "error-project",
            name: "Rorze",
            slug: "rorze",
            ingest_state: "error",
            is_active: false,
          },
          {
            ...projects[0],
            id: "ready-project",
            name: "VFIC Express",
            slug: "vfic-express",
            ingest_state: "ready",
            is_active: true,
          },
          {
            ...projects[1],
            id: "draft-project",
            name: "4P Electronic",
            slug: "4p-electronic",
            ingest_state: null,
            is_active: false,
          },
        ]}
        isAdmin={false}
        canEdit={false}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    expect(badgeLabels(screen.container)).toEqual([
      ["Đang bật", "Đang nạp", "Theo danh mục"],
      ["Đã tắt", "Lỗi nạp", "Theo danh mục"],
      ["Đang bật", "Đã nạp", "Theo danh mục"],
      ["Đã tắt", "Một trang"],
    ]);
    await expect.element(screen.getByText("Đang nạp")).toBeVisible();
    await expect.element(screen.getByText("Lỗi nạp")).toBeVisible();
  });

  it("shows no ingest badge when the payload says nothing about ingest", async () => {
    const legacyActive: Project = {
      id: "legacy-active",
      name: "Dự án cũ đang bật",
      slug: "du-an-cu-dang-bat",
      is_active: true,
      knowledge_mode: "RAG",
      knowledge_document_count: 2,
      category_readiness: { ready: 2, total: 12 },
      created_at: "2026-07-18T00:00:00Z",
      updated_at: "2026-07-18T00:00:00Z",
    };
    const screen = await render(
      <ProjectAccordionList
        projects={[legacyActive, { ...projects[1], ingest_state: null }]}
        isAdmin={false}
        canEdit={false}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    expect(badgeLabels(screen.container)).toEqual([
      ["Đang bật", "Theo danh mục"],
      ["Đã tắt", "Một trang"],
    ]);
  });

  it("does not claim trained knowledge for an active project with no documents", async () => {
    const screen = await render(
      <ProjectAccordionList
        projects={[{ ...projects[0], knowledge_document_count: 0 }]}
        isAdmin={false}
        canEdit={false}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );
    expect(badgeLabels(screen.container)).toEqual([
      ["Đang bật", "Chưa nạp", "Theo danh mục"],
    ]);
  });

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
      .element(
        screen.getByRole("button", { name: "Bật dự án Dự án một trang" }),
      )
      .toBeVisible();
  });

  it.each(["ingesting", "error"] as const)(
    "keeps a draft inactive while its knowledge is %s",
    async (ingest_state) => {
      const screen = await render(
        <ProjectAccordionList
          projects={[{ ...projects[0], is_active: false, ingest_state }]}
          isAdmin={false}
          canEdit
          onEdit={vi.fn()}
          onDeleted={vi.fn()}
          onToggleActive={vi.fn()}
        />,
      );
      await screen
        .getByRole("button", {
          name: "Mở hoặc đóng kiến thức dự án LG Display",
        })
        .click();
      await expect
        .element(screen.getByRole("button", { name: "Bật dự án LG Display" }))
        .toBeDisabled();
      await expect
        .element(screen.getByText(/Hoàn tất nạp và xử lý lỗi kiến thức/))
        .toBeVisible();
    },
  );

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
