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
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectKnowledgePanel } from "./ProjectKnowledgePanel";
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

  return (
    <ProjectWorkspaceShell>
      <div className="project-workspace-content">
        <div className="project-editor-header flex flex-wrap items-start gap-3 rounded-lg border p-4">
          <div className="mr-auto min-w-0">
            <p className="text-helper font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Dự án
            </p>
            <h1 className="mt-1 truncate text-content-title font-semibold">
              Chỉnh sửa {project.name}
            </h1>
            <p className="mt-1 text-body text-muted-foreground">
              Cập nhật trạng thái và nguồn tri thức dùng khi tư vấn ứng viên.
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
            <CardTitle className="flex items-center justify-between text-section-title">
              <span>{project.name}</span>
              <div className="flex gap-2">
                <Badge variant="outline">
                  {project.knowledge_mode === "DIRECT_CONTEXT"
                    ? "Một trang"
                    : "Theo danh mục"}
                </Badge>
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
              </div>
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

        <div className="project-detail-stack mt-4">
          <ProjectKnowledgePanel project={project} editable={isAdmin} />
        </div>
      </div>
    </ProjectWorkspaceShell>
  );
};

export const ProjectEdit = () => (
  <EditBase>
    <ProjectEditContent />
  </EditBase>
);
