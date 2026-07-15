import { useEffect, useState } from "react";
import {
  EditBase,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
} from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TopToolbar } from "../layout/TopToolbar";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { KnowledgeSource } from "../types";
import { ProjectPicker } from "./ProjectPicker";

const KnowledgeSourceEditContent = () => {
  const source = useRecordContext<KnowledgeSource>();
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [submitting, setSubmitting] = useState(false);
  const [fileName, setFileName] = useState("");
  const [projectId, setProjectId] = useState("");

  useEffect(() => {
    if (!source) return;
    setFileName(source.file_name);
    setProjectId(source.project_id ?? "");
  }, [source]);

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
        <CardTitle className="text-section-title">Thông tin tài liệu</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-label font-medium">
            Tên tài liệu
            <Input
              value={fileName}
              onChange={(event) => setFileName(event.target.value)}
              required
            />
          </label>
          <label className="flex flex-col gap-1.5 text-label font-medium">
            Dự án
            <ProjectPicker value={projectId} onChange={setProjectId} />
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
      <h2 className="mr-auto text-content-title font-semibold">
        Chỉnh sửa cơ sở kiến thức
      </h2>
    </TopToolbar>
    <KnowledgeSourceEditContent />
  </EditBase>
);
