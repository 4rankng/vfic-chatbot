import { useEffect, useState } from "react";
import {
  EditBase,
  useDataProvider,
  useNotify,
  useRecordContext,
  useRedirect,
} from "ra-core";
import { ArrowLeft, FileText, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TopToolbar } from "../layout/TopToolbar";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { KnowledgeSource } from "../types";
import { ProjectPicker } from "./ProjectPicker";
import "../conversations/inbox.css";

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

  const normalizedFileName = fileName.trim();
  const hasChanges =
    normalizedFileName !== source.file_name ||
    projectId !== (source.project_id ?? "");
  const canSubmit =
    normalizedFileName.length > 0 &&
    projectId.length > 0 &&
    hasChanges &&
    !submitting;

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;

    setSubmitting(true);
    try {
      await dataProvider.update("knowledge_sources", {
        id: source.id,
        previousData: source,
        data: {
          file_name: normalizedFileName,
          project_id: projectId,
        },
      });
      notify("Đã lưu thay đổi.", { type: "success" });
      redirect("show", "knowledge_sources", source.id);
    } catch (error) {
      notify(`Không thể lưu: ${(error as Error).message}`, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="kb-scope knowledge-source-subpage knowledge-source-edit-page">
      <TopToolbar className="knowledge-source-subpage-toolbar justify-start">
        <Button
          type="button"
          variant="ghost"
          className="tt-btn-touch h-11 rounded-[9px]"
          onClick={() => redirect("list", "knowledge_sources")}
        >
          <ArrowLeft className="size-4" />
          Tất cả nguồn
        </Button>
      </TopToolbar>

      <header className="knowledge-source-edit-header">
        <div className="knowledge-source-edit-mark" aria-hidden="true">
          <FileText className="size-5" />
        </div>
        <div className="min-w-0">
          <p className="ops-kicker">Nguồn kiến thức</p>
          <h1>Chỉnh sửa nguồn</h1>
          <p>{source.file_name}</p>
        </div>
      </header>

      <form
        onSubmit={onSubmit}
        className="knowledge-source-edit-form"
        aria-busy={submitting}
      >
        <div className="knowledge-source-edit-form-header">
          <h2>Thông tin tài liệu</h2>
          <span>{source.mime_type || "Tài liệu"}</span>
        </div>

        <div className="knowledge-source-edit-fields">
          <label htmlFor="knowledge-source-name">Tên tài liệu</label>
          <Input
            id="knowledge-source-name"
            value={fileName}
            onChange={(event) => setFileName(event.target.value)}
            className="h-11"
            required
          />

          <label htmlFor="knowledge-source-project">Dự án</label>
          <ProjectPicker
            id="knowledge-source-project"
            value={projectId}
            onChange={setProjectId}
          />
        </div>

        <footer className="knowledge-source-edit-actions">
          <Button
            type="button"
            variant="outline"
            className="tt-btn-touch h-11 rounded-[9px]"
            disabled={submitting}
            onClick={() =>
              redirect("show", "knowledge_sources", source.id)
            }
          >
            Hủy
          </Button>
          <Button
            type="submit"
            className="tt-btn-touch h-11 rounded-[9px]"
            disabled={!canSubmit}
          >
            {submitting && (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
            )}
            {submitting ? "Đang lưu…" : "Lưu thay đổi"}
          </Button>
        </footer>
      </form>
    </main>
  );
};

export const KnowledgeSourceEdit = () => (
  <EditBase>
    <KnowledgeSourceEditContent />
  </EditBase>
);
