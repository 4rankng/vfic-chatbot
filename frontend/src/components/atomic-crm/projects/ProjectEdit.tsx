import { useState } from "react";
import {
  EditBase,
  Form,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
  useTranslate,
} from "ra-core";
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
  const translate = useTranslate();
  const { isAdmin, canEdit } = useRoleActions();
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
        <div className="project-editor-header project-form-page-header flex flex-wrap items-start gap-3">
          <div className="mr-auto min-w-0">
            <p className="text-helper font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Dự án
            </p>
            <h1 className="mt-1 truncate text-content-title font-semibold">
              {project.name}
            </h1>
            <div
              className="project-edit-meta mt-1"
              aria-label="Trạng thái dự án"
            >
              <span
                className={
                  project.is_active ? "text-success" : "text-muted-foreground"
                }
              >
                <span className="project-edit-status-dot" aria-hidden="true" />
                {project.is_active ? "Đang hoạt động" : "Đang tắt"}
              </span>
              <span aria-hidden="true">·</span>
              <span>
                {project.knowledge_mode === "DIRECT_CONTEXT"
                  ? "Một nội dung"
                  : "Theo danh mục"}
              </span>
            </div>
          </div>
          {isAdmin && (
            <DeleteButton
              label="Xóa dự án"
              successMessage="Đã xóa dự án."
              redirect="list"
            />
          )}
        </div>

        <section
          className="project-form-surface project-edit-form-surface mt-4"
          aria-label="Cài đặt dự án"
        >
          <Form record={project} onSubmit={onSubmit}>
            <div className="project-edit-settings">
              <TextInput
                source="name"
                label="Tên dự án"
                className="project-edit-name"
                isRequired
              />
              <BooleanInput
                source="is_active"
                label="Dự án hoạt động"
                className="project-edit-active"
              />
              <Button
                type="submit"
                className="project-edit-save"
                disabled={submitting}
              >
                {translate("crm.common.save_changes")}
              </Button>
            </div>
          </Form>
        </section>

        <div className="project-detail-stack mt-4">
          <ProjectKnowledgePanel
            project={project}
            editable={canEdit}
            canManageSources={isAdmin}
          />
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
