import { useState } from "react";
import {
  EditBase,
  Form,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
} from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TextInput } from "@/components/admin/text-input";
import { BooleanInput } from "@/components/admin/boolean-input";
import { Button } from "@/components/ui/button";
import { Upload } from "lucide-react";
import { KnowledgeUpload } from "../knowledge/KnowledgeUpload";
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectFeatures } from "./ProjectFeatures";
import { ProjectFaqEditor } from "./ProjectFaqEditor";
import { ProjectPersonaPanel } from "./ProjectPersonaPanel";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Project } from "../types";
import { DeleteButton } from "@/components/admin";

const ProjectEditContent = () => {
  const project = useRecordContext<Project>();
  const notify = useNotify();
  const redirect = useRedirect();
  const { isAdmin } = useRoleActions();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [submitting, setSubmitting] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  if (!project) return null;

  const onSubmit = async (data: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      await dataProvider.update("projects", {
        id: project.id,
        previousData: project,
        data,
      });
      notify("Đã lưu.", { type: "success" });
      redirect("/projects");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  const card = project.index_card ?? {};
  return (
    <ProjectWorkspaceShell>
      <div className="project-workspace-content">
        <div className="project-editor-header flex flex-wrap items-start gap-3 rounded-lg border p-4">
          <div className="mr-auto min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Dự án
            </p>
            <h2 className="mt-1 truncate text-xl font-semibold">
              Chỉnh sửa {project.name}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Cập nhật trạng thái, Agent mặc định và nguồn tri thức dùng khi tư
              vấn ứng viên.
            </p>
          </div>
          {isAdmin && (
            <DeleteButton
              label="Xóa dự án"
              successMessage="Đã xóa dự án."
              redirect="list"
            />
          )}
        </div>

        <Card className="mt-4 max-w-2xl">
          <CardHeader>
            <CardTitle className="flex items-center justify-between text-base">
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
          <CardContent className="pt-2">
            <Form record={project} onSubmit={onSubmit}>
              <div className="flex flex-col gap-4">
                <TextInput source="name" label="Tên dự án" isRequired />
                <BooleanInput source="is_active" label="Đang hoạt động" />
                <Button type="submit" disabled={submitting}>
                  Lưu
                </Button>
              </div>
            </Form>
          </CardContent>
        </Card>

        {isAdmin && <ProjectPersonaPanel project={project} />}

        <Card className="mt-4 max-w-2xl">
          <CardHeader>
            <CardTitle className="flex items-center justify-between text-base">
              <span>Thẻ danh mục (master index)</span>
              {isAdmin && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setUploadOpen(true)}
                  title="Tải tin tuyển dụng lên cho dự án này"
                >
                  <Upload className="size-4" />
                  Tải tin lên
                </Button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 pt-2 text-sm">
            <p>
              <span className="text-muted-foreground">Tóm tắt: </span>
              {project.summary ?? "—"}
            </p>
            <p>
              <span className="text-muted-foreground">Địa điểm: </span>
              {card.location ?? "—"}
            </p>
            <p>
              <span className="text-muted-foreground">Vị trí: </span>
              {(card.key_roles ?? []).join(", ") || "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              Thẻ được LLM tạo tự động khi huấn luyện cơ sở kiến thức của dự án.
            </p>
          </CardContent>
        </Card>

        <div className="project-detail-stack mt-4">
          <ProjectFeatures
            projectId={project.id}
            editable
            canExtract={isAdmin}
          />
          <ProjectFaqEditor projectId={project.id} editable />
        </div>

        {isAdmin && (
          <KnowledgeUpload
            open={uploadOpen}
            onOpenChange={setUploadOpen}
            initialProjectId={project.id}
            lockProject
          />
        )}
      </div>
    </ProjectWorkspaceShell>
  );
};

export const ProjectEdit = () => (
  <EditBase>
    <ProjectEditContent />
  </EditBase>
);
