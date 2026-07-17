import { useState } from "react";
import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
  useGetList,
} from "ra-core";
import { Card, CardContent } from "@/components/ui/card";
import { TextInput } from "@/components/admin/text-input";
import { BooleanInput } from "@/components/admin/boolean-input";
import { Button } from "@/components/ui/button";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";
import { SelectInput } from "@/components/admin/select-input";
import type { KnowledgeBase } from "../types";

export const ProjectCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [submitting, setSubmitting] = useState(false);
  const { data: knowledgeBases = [] } = useGetList<KnowledgeBase>("knowledge_bases", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
    filter: {},
  });
  const ragKnowledgeBases = knowledgeBases.filter((knowledgeBase) => knowledgeBase.mode === "RAG");

  const onSubmit = async (data: Record<string, unknown>) => {
    if (!data.knowledge_base_id) {
      notify("Vui lòng chọn Knowledge Base RAG cho dự án.", { type: "warning" });
      return;
    }
    setSubmitting(true);
    try {
      await dataProvider.create("projects", { data });
      notify("Đã tạo dự án.", { type: "success" });
      redirect("/projects");
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <CreateBase resource="projects">
      <ProjectWorkspaceShell>
        <div className="project-workspace-content">
          <div className="project-editor-header rounded-lg border p-4">
            <p className="text-helper font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Dự án
            </p>
            <h1 className="mt-1 text-content-title font-semibold">Tạo dự án</h1>
            <p className="mt-1 text-body text-muted-foreground">
              Tạo không gian huấn luyện riêng cho một dự án tuyển dụng.
            </p>
          </div>
          <Card className="mt-4 max-w-2xl">
            <CardContent className="pt-6">
              <Form onSubmit={onSubmit}>
                <div className="flex flex-col gap-4">
                  <TextInput source="name" label="Tên dự án" isRequired />
                  <TextInput
                    source="slug"
                    label="Slug (không dấu, không khoảng cách)"
                    isRequired
                  />
                  <SelectInput
                    source="knowledge_base_id"
                    label="Knowledge Base RAG"
                    choices={ragKnowledgeBases.map((knowledgeBase) => ({
                      id: knowledgeBase.id,
                      name: knowledgeBase.name,
                    }))}
                    emptyText="Chọn Knowledge Base"
                    isRequired
                  />
                  <BooleanInput
                    source="is_active"
                    label="Đang hoạt động"
                    defaultValue={true}
                  />
                  <Button type="submit" disabled={submitting || ragKnowledgeBases.length === 0}>
                    Tạo dự án
                  </Button>
                </div>
              </Form>
            </CardContent>
          </Card>
        </div>
      </ProjectWorkspaceShell>
    </CreateBase>
  );
};
