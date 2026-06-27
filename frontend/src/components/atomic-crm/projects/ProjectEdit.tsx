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
import { TopToolbar } from "../layout/TopToolbar";
import { Button } from "@/components/ui/button";
import { Upload } from "lucide-react";
import { KnowledgeUpload } from "../knowledge/KnowledgeUpload";
import { ProjectFeatures } from "./ProjectFeatures";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Project } from "../types";

const ProjectEditContent = () => {
  const project = useRecordContext<Project>();
  const notify = useNotify();
  const redirect = useRedirect();
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
        data: { ...data, id: project.id },
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
    <>
      <Card className="mt-4 max-w-2xl">
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span>{project.name}</span>
            <Badge variant={project.is_active ? "default" : "outline"}>
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

      <Card className="mt-4 max-w-2xl">
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span>Thẻ danh mục (master index)</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setUploadOpen(true)}
              title="Tải tin tuyển dụng lên cho dự án này"
            >
              <Upload className="size-4" />
              Tải tin lên
            </Button>
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
            Bấm "Làm mới thẻ" trong danh sách để tạo lại.
          </p>
        </CardContent>
      </Card>

      <ProjectFeatures projectId={project.id} />

      <KnowledgeUpload
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        initialProjectId={project.id}
        lockProject
      />
    </>
  );
};

export const ProjectEdit = () => (
  <EditBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Chỉnh sửa dự án</h2>
    </TopToolbar>
    <ProjectEditContent />
  </EditBase>
);
