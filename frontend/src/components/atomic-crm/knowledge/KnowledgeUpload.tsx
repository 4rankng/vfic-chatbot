import { useState } from "react";
import { useGetList, useNotify, useRefresh } from "ra-core";
import { CheckCircle2, FileText, RefreshCw, UploadCloud } from "lucide-react";
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

  const effectiveProjectId = lockProject ? (initialProjectId ?? "") : projectId;

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
      notify(
        "Đã tải lên. Đang huấn luyện + trích xuất đặc điểm (chạy ở nền).",
        {
          type: "success",
        },
      );
      reset();
      onOpenChange(false);
      refresh();
    } catch (err) {
      notify(`Tải lên thất bại: ${(err as Error).message}`, { type: "error" });
    } finally {
      setBusy(false);
    }
  };

  const ModeTab = ({
    value,
    label,
  }: {
    value: "file" | "paste";
    label: string;
  }) => (
    <button
      type="button"
      onClick={() => setMode(value)}
      className={cn(
        "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        mode === value
          ? "border border-border bg-background text-foreground shadow-sm"
          : "bg-muted text-muted-foreground hover:bg-muted/70",
      )}
    >
      {label}
    </button>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Tải cơ sở kiến thức lên</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto py-2 pr-1">
          <div className="rounded-xl border border-[#dfe4d8] bg-[#f7f7f4] p-3">
            <div className="flex items-start gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[#111111] text-white">
                {busy ? (
                  <RefreshCw className="size-5 animate-spin" />
                ) : (
                  <UploadCloud className="size-5" />
                )}
              </span>
              <div>
                <p className="text-sm font-semibold">
                  {busy
                    ? "Đang gửi vào pipeline ingest"
                    : "Sau khi tải lên, pipeline sẽ tự chạy"}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Tệp sẽ đi qua nhận file, trích văn bản, digest bằng LLM, nhúng
                  vector và xuất bản để agent có thể truy xuất.
                </p>
              </div>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-4">
              <UploadStep
                done
                icon={<FileText className="size-4" />}
                label="Nhận tệp"
              />
              <UploadStep
                done={busy}
                icon={<RefreshCw className="size-4" />}
                label="Trích xuất"
              />
              <UploadStep
                icon={<RefreshCw className="size-4" />}
                label="Digest"
              />
              <UploadStep
                icon={<CheckCircle2 className="size-4" />}
                label="Sẵn sàng"
              />
            </div>
          </div>

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
                <span className="text-xs text-muted-foreground">
                  {file.name}
                </span>
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
                className="max-h-[40vh] min-h-48 resize-y overflow-y-auto text-sm"
              />
            </div>
          )}
        </div>
        <DialogFooter className="shrink-0 border-t pt-3">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            Hủy
          </Button>
          <Button
            className="bg-[#111111] text-white hover:bg-[#2a2a2a]"
            onClick={submit}
            disabled={busy}
          >
            {busy ? "Đang tải lên..." : "Tải lên"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

const UploadStep = ({
  done,
  icon,
  label,
}: {
  done?: boolean;
  icon: React.ReactNode;
  label: string;
}) => (
  <div
    className={cn(
      "flex min-w-0 items-center gap-2 rounded-lg px-2 py-2 text-xs",
      done ? "bg-white text-[#111111]" : "bg-[#eef0ea] text-muted-foreground",
    )}
  >
    <span
      className={cn(
        "flex size-6 shrink-0 items-center justify-center rounded-md",
        done ? "bg-[#e8f5ec] text-[#1f7a4d]" : "bg-white text-muted-foreground",
      )}
    >
      {icon}
    </span>
    <span className="truncate font-medium">{label}</span>
  </div>
);
