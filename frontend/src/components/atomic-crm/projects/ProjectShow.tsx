import { ShowBase, useRecordContext, useRedirect } from "ra-core";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { ArrowLeft, Pencil } from "lucide-react";
import type { Project } from "../types";
import { ProjectKnowledgePanel } from "./ProjectKnowledgePanel";
import { DeleteButton } from "@/components/admin";
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";
import { projectKnowledgeModeLabel } from "./domain/project-knowledge-policy";

const ProjectShowContent = () => {
  const project = useRecordContext<Project>();
  const redirect = useRedirect();
  const { isAdmin, canEdit } = useRoleActions();
  if (!project) return null;

  const card = project.index_card ?? {};
  // Projection-built cards write `roles`; legacy/LLM cards write `key_roles`.
  const roles = Array.from(new Set(card.roles ?? card.key_roles ?? []));

  return (
    <ProjectWorkspaceShell>
      <div className="project-workspace-content">
        <header className="project-editor-header project-form-page-header project-show-page-header">
          <Button
            type="button"
            color="link-gray"
            size="sm"
            className="uu-scope project-back-link"
            iconLeading={ArrowLeft}
            onClick={() => redirect("/projects")}
          >
            Dự án
          </Button>
          <h1 className="mt-1 text-content-title font-semibold">
            {project.name}
          </h1>
          <p className="mt-1 text-body text-muted-foreground">
            Thông tin tuyển dụng và kiến thức chatbot dùng để tư vấn ứng viên.
          </p>
        </header>
        <div className="project-show-layout">
          <section className="project-show-summary">
            <header className="project-show-summary-header flex items-center justify-between gap-2 text-section-title">
              <span>Thông tin</span>
              <Badge
                className="uu-scope"
                type="pill-color"
                size="sm"
                color={project.is_active ? "success" : "gray"}
              >
                {project.is_active ? "Đang hoạt động" : "Tắt"}
              </Badge>
            </header>
            <div className="project-show-summary-content text-body">
              <div className="project-show-fact">
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Mã dự án
                </div>
                <div className="font-mono">{project.slug}</div>
              </div>
              <div className="project-show-fact">
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Cách lưu kiến thức
                </div>
                <p>{projectKnowledgeModeLabel(project.knowledge_mode)}</p>
              </div>
              <div className="project-show-fact">
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Tóm tắt
                </div>
                <p>{project.summary ?? "—"}</p>
              </div>
              <div className="project-show-fact">
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Địa điểm
                </div>
                <p>{card.location ?? "—"}</p>
              </div>
              <div className="project-show-fact">
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Vị trí tuyển dụng
                </div>
                <p>{roles.join(", ") || "—"}</p>
              </div>
              <div className="project-show-summary-actions">
                {canEdit && (
                  <Button
                    color="secondary"
                    size="sm"
                    className="uu-scope w-fit"
                    iconLeading={Pencil}
                    onClick={() => redirect("edit", "projects", project.id)}
                  >
                    Quản lý dự án
                  </Button>
                )}
                {isAdmin && (
                  <DeleteButton
                    label="Xóa"
                    size="sm"
                    successMessage="Đã xóa dự án."
                    redirect="list"
                  />
                )}
              </div>
            </div>
          </section>

          <div className="project-detail-stack">
            <ProjectKnowledgePanel
              project={project}
              editable={canEdit}
              canManageSources={isAdmin}
            />
          </div>
        </div>
      </div>
    </ProjectWorkspaceShell>
  );
};

export const ProjectShow = () => (
  <ShowBase>
    <ProjectShowContent />
  </ShowBase>
);
