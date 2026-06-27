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
import { Textarea } from "@/components/ui/textarea";
import { uploadKnowledgeFile } from "@/lib/vfic/knowledgeService";
import type { Project } from "../types";
import { cn } from "@/lib/utils";

interface KnowledgeUploadProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-select a project (used when opening from the Project editor). */
  initialProjectId?: string;
  /** Hide the project selector — upload is bound to initialProjectId. */
  lockProject?: boolean;
}

// KB upload for a project (product). Two modes: pick an Office/text file, or paste raw
// text. Paste is built into a .txt File so it reuses upload-file (which enqueues the
// training pipeline) — the JSON /documents/upload route does NOT enqueue training.
export const KnowledgeUpload = ({
  open,
  onOpenChange,
  initialProjectId,
  lockProject = false,
}: KnowledgeUploadProps) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const { data: projects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
  });
  const [projectId, setProjectId] = useState<string>(initialProjectId ?? "");
  const [mode, setMode] = useState<"file" | "paste">("file");
  const [file, setFile] = useState<File | null>(null);
  const [pasteText, setPasteText] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const effectiveProjectId = lockProject ? initialProjectId ?? "" : projectId;

  const reset = () => {
    setFile(null);
    setPasteText("");
    setMode("file");
    setProjectId(initialProjectId ?? "");
  };

  const submit = async () => {
    const payload: File | null =
      mode === "paste"
        ? pasteText.trim()
          ? new File([pasteText], "tin-tuyen-dung.txt", { type: "text/plain" })
          : null
        : file;
    if (!payload) {
      notify("Vui lòng chọn tệp hoặc dán nội dung.", { type: "warning" });
      return;
    }
    setBusy(true);
    try {
      await uploadKnowledgeFile(payload, effectiveProjectId || null);
      notify("Đã tải lên. Đang huấn luyện + trích xuất đặc điểm (chạy ở nền).", {
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

  const ModeTab = ({ value, label }: { value: "file" | "paste"; label: string }) => (
    <button
      type="button"
      onClick={() => setMode(value)}
      className={cn(
        "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        mode === value
          ? "bg-primary text-primary-foreground"
          : "bg-muted text-muted-foreground hover:bg-muted/70",
      )}
    >
      {label}
    </button>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Tải cơ sở kiến thức lên</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-2">
          {!lockProject && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Dự án (sản phẩm)
              </label>
              <Select value={effectiveProjectId} onValueChange={setProjectId}>
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
          )}

          <div className="flex gap-1.5">
            <ModeTab value="file" label="Chọn tệp" />
            <ModeTab value="paste" label="Dán văn bản" />
          </div>

          {mode === "file" ? (
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
          ) : (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Dán nội dung tin tuyển dụng
              </label>
              <Textarea
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                rows={10}
                placeholder="Dán toàn bộ nội dung tin tuyển dụng vào đây..."
                className="text-sm"
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Hủy
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? "Đang tải lên..." : "Tải lên"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
