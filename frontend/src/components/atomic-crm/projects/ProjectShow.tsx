import { ShowBase, useRecordContext, useRedirect } from "ra-core";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Pencil } from "lucide-react";
import type { Project } from "../types";
import { ProjectKnowledgePanel } from "./ProjectKnowledgePanel";
import { DeleteButton } from "@/components/admin";
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

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
        <div className="project-editor-header">
          <h1 className="mt-1 text-content-title font-semibold">
            {project.name}
          </h1>
          <p className="mt-1 text-body text-muted-foreground">
            Xem danh mục kiến thức, đặc điểm sản phẩm và FAQ mà chatbot dùng
            trong hội thoại tuyển dụng.
          </p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
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
            <div className="project-show-summary-content flex flex-col text-body">
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
                <p>
                  {project.knowledge_mode === "DIRECT_CONTEXT"
                    ? "Một trang"
                    : "Theo danh mục"}
                </p>
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
              <div className="project-show-summary-actions mt-1 flex flex-wrap gap-2">
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
