import { useState } from "react";
import { useGetList, useNotify, useRefresh } from "ra-core";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { uploadKnowledgeFile } from "@/lib/vfic/knowledgeService";
import type { Project } from "../types";

interface KnowledgeUploadProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Multipart KB upload: pick a project, choose an Office/text file, POST to
// /knowledge/documents/upload-file. The backend extracts text and enqueues the
// LLM training pipeline (digest -> embed -> index); the list refresh shows stage.
export const KnowledgeUpload = ({ open, onOpenChange }: KnowledgeUploadProps) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const { data: projects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
  });
  const [projectId, setProjectId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setFile(null);
    setProjectId("");
  };

  const submit = async () => {
    if (!file) {
      notify("Vui lòng chọn tệp.", { type: "warning" });
      return;
    }
    setBusy(true);
    try {
      await uploadKnowledgeFile(file, projectId || null);
      notify("Đã tải lên. Đang huấn luyện (quá trình LLM chạy ở nền).", {
        type: "success",
      });
      reset();
      onOpenChange(false);
      refresh();
    } catch (err) {
      notify(`Tải lên thất bại: ${(err as Error).message}`, { type: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Tải lên cơ sở kiến thức</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Dự án (sản phẩm)
            </label>
            <Select value={projectId} onValueChange={setProjectId}>
              <SelectTrigger>
                <SelectValue placeholder="— Không chọn (chung) —" />
              </SelectTrigger>
              <SelectContent>
                {(projects ?? []).map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name} ({p.slug})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Tệp (PDF, DOCX, XLSX, CSV, TXT, MD)
            </label>
            <input
              type="file"
              accept=".pdf,.docx,.xlsx,.csv,.txt,.md"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm"
            />
            {file && (
              <span className="text-xs text-muted-foreground">{file.name}</span>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            Hủy
          </Button>
          <Button onClick={submit} disabled={busy || !file}>
            {busy ? "Đang tải lên..." : "Tải lên"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
