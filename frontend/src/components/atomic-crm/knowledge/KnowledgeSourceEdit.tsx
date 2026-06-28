import { useEffect, useState } from "react";
import {
  EditBase,
  useDataProvider,
  useGetList,
  useNotify,
  useRecordContext,
  useRedirect,
} from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TopToolbar } from "../layout/TopToolbar";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { KnowledgeSource, Project } from "../types";

const KnowledgeSourceEditContent = () => {
  const source = useRecordContext<KnowledgeSource>();
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const { data: projects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
  });
  const [submitting, setSubmitting] = useState(false);
  const [fileName, setFileName] = useState("");
  const [projectId, setProjectId] = useState("");

  useEffect(() => {
    if (!source) return;
    setFileName(source.file_name);
    setProjectId(source.project_id ?? projects?.[0]?.id ?? "");
  }, [projects, source]);

  if (!source) return null;

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await dataProvider.update("knowledge_sources", {
        id: source.id,
        previousData: source,
        data: {
          file_name: fileName,
          project_id: projectId,
        },
      });
      notify("Đã lưu cơ sở kiến thức.", { type: "success" });
      redirect("show", "knowledge_sources", source.id);
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card className="mt-4 max-w-2xl">
      <CardHeader>
        <CardTitle className="text-base">Thông tin tài liệu</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm font-medium">
            Tên tài liệu
            <Input
              value={fileName}
              onChange={(event) => setFileName(event.target.value)}
              required
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm font-medium">
            Dự án
            <Select value={projectId} onValueChange={setProjectId}>
              <SelectTrigger>
                <SelectValue placeholder="Chọn dự án" />
              </SelectTrigger>
              <SelectContent>
                {(projects ?? []).map((project) => (
                  <SelectItem key={project.id} value={project.id}>
                    {project.name} ({project.slug})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          <Button type="submit" disabled={submitting || !projectId}>
            {submitting ? "Đang lưu..." : "Lưu"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};

export const KnowledgeSourceEdit = () => (
  <EditBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Chỉnh sửa cơ sở kiến thức</h2>
    </TopToolbar>
    <KnowledgeSourceEditContent />
  </EditBase>
);
