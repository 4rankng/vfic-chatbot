import { useState } from "react";
import { ShowBase, useRecordContext, useRedirect } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Pencil, Upload } from "lucide-react";
import type { Project } from "../types";
import { ProjectFeatures } from "./ProjectFeatures";
import { ProjectFaqEditor } from "./ProjectFaqEditor";
import { DeleteButton } from "@/components/admin";
import { KnowledgeUpload } from "../knowledge/KnowledgeUpload";
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

const ProjectShowContent = () => {
  const project = useRecordContext<Project>();
  const redirect = useRedirect();
  const { isAdmin, canEdit } = useRoleActions();
  const [uploadOpen, setUploadOpen] = useState(false);
  if (!project) return null;

  const card = project.index_card ?? {};

  return (
    <ProjectWorkspaceShell
      total={1}
      activeCount={project.is_active ? 1 : 0}
      documentCount={project.knowledge_document_count ?? 0}
    >
      <div className="project-workspace-content">
        <div className="project-editor-header rounded-lg border p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Đặc điểm dự án
          </p>
          <h2 className="mt-1 text-xl font-semibold">{project.name}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Xem thẻ danh mục, đặc điểm sản phẩm và FAQ mà Agent dùng trong hội
            thoại tuyển dụng.
          </p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2 text-base">
                <span>{project.name}</span>
                <Badge
                  variant="outline"
                  className={
                    project.is_active
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                      : "border-border bg-muted/40 text-muted-foreground"
                  }
                >
                  {project.is_active ? "Đang hoạt động" : "Tắt"}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Mã dự án
                </div>
                <div className="font-mono">{project.slug}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Tóm tắt
                </div>
                <p>{project.summary ?? "—"}</p>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Địa điểm
                </div>
                <p>{card.location ?? "—"}</p>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Vị trí
                </div>
                <p>{(card.key_roles ?? []).join(", ") || "—"}</p>
              </div>
              <div className="mt-1 flex flex-wrap gap-2">
                {isAdmin && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-fit"
                    onClick={() => setUploadOpen(true)}
                  >
                    <Upload className="size-4" />
                    Thêm tệp
                  </Button>
                )}
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
            <ProjectFeatures
              projectId={project.id}
              editable={canEdit}
              canExtract={isAdmin}
            />
            <ProjectFaqEditor projectId={project.id} editable={canEdit} />
          </div>
          <KnowledgeUpload
            open={uploadOpen}
            onOpenChange={setUploadOpen}
            initialProjectId={project.id}
            lockProject
          />
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
