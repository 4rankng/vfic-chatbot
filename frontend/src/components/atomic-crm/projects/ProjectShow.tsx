import { ShowBase, useRecordContext, useRedirect } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

  return (
    <ProjectWorkspaceShell>
      <div className="project-workspace-content">
        <div className="project-editor-header">
          <h2 className="mt-1 text-content-title font-semibold">{project.name}</h2>
          <p className="mt-1 text-body text-muted-foreground">
            Xem thẻ danh mục, đặc điểm sản phẩm và FAQ mà Agent dùng trong hội
            thoại tuyển dụng.
          </p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2 text-section-title">
                <span>{project.name}</span>
                <Badge
                  variant="outline"
                  className={
                    project.is_active
                      ? "tt-badge-success tt-badge-soft border-transparent text-success"
                      : "border-border bg-muted/40 text-muted-foreground"
                  }
                >
                  {project.is_active ? "Đang hoạt động" : "Tắt"}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-body">
              <div>
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Mã dự án
                </div>
                <div className="font-mono">{project.slug}</div>
              </div>
              <div>
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Cách lưu kiến thức
                </div>
                <p>
                  {project.knowledge_mode === "DIRECT_CONTEXT"
                    ? "Một trang"
                    : "Theo danh mục"}
                </p>
              </div>
              <div>
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Tóm tắt
                </div>
                <p>{project.summary ?? "—"}</p>
              </div>
              <div>
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Địa điểm
                </div>
                <p>{card.location ?? "—"}</p>
              </div>
              <div>
                <div className="text-helper uppercase tracking-wide text-muted-foreground">
                  Vị trí
                </div>
                <p>{(card.key_roles ?? []).join(", ") || "—"}</p>
              </div>
              <div className="mt-1 flex flex-wrap gap-2">
                {canEdit && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-fit"
                    onClick={() => redirect("edit", "projects", project.id)}
                  >
                    <Pencil className="size-4" />
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
            </CardContent>
          </Card>

          <div className="project-detail-stack">
            <ProjectKnowledgePanel project={project} editable={isAdmin} />
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
