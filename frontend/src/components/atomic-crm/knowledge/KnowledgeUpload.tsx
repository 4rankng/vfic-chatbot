import { useEffect, useState } from "react";
import { useGetList, useNotify, useRefresh } from "ra-core";
import {
  CheckCircle2,
  ClipboardList,
  Download,
  FileText,
  RefreshCw,
  UploadCloud,
  X,
} from "lucide-react";
import { useDropzone, type FileRejection } from "react-dropzone";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  saveKnowledgeTemplate,
  uploadKnowledgeFile,
} from "@/lib/vfic/knowledgeService";
import type { Project } from "../types";
import { cn } from "@/lib/utils";
import {
  ACCEPTED_KNOWLEDGE_TYPES,
  formatFileSize,
} from "./knowledgeUploadConfig";

interface KnowledgeUploadProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-select a project (used when opening from the Project editor). */
  initialProjectId?: string;
  /** Hide the project selector — upload is bound to initialProjectId. */
  lockProject?: boolean;
}

// KB upload for a project (product). Two modes: pick a source file (.md/.txt/.docx),
// or paste raw text. Paste is built into a .txt File so it reuses upload-file (which
// enqueues the training pipeline) — the JSON /documents/upload route does NOT enqueue.
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
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  const effectiveProjectId = lockProject ? (initialProjectId ?? "") : projectId;
  const canSubmit =
    !busy &&
    !!effectiveProjectId &&
    (mode === "paste" ? pasteText.trim().length > 0 : file !== null);

  useEffect(() => {
    if (!open || lockProject || projectId || !projects?.[0]?.id) return;
    setProjectId(projects[0].id);
  }, [lockProject, open, projectId, projects]);

  useEffect(() => {
    if (!open || !initialProjectId) return;
    setProjectId(initialProjectId);
  }, [initialProjectId, open]);

  const reset = () => {
    setFile(null);
    setPasteText("");
    setMode("file");
    setProjectId(initialProjectId ?? "");
    setValidationErrors([]);
  };

  const handleRejectedFiles = (rejections: FileRejection[]) => {
    if (rejections.length === 0) return;
    notify("Tệp không hợp lệ. Chỉ hỗ trợ .md, .txt hoặc .docx.", {
      type: "warning",
    });
  };

  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      accept: ACCEPTED_KNOWLEDGE_TYPES,
      disabled: busy,
      maxFiles: 1,
      multiple: false,
      onDrop: (acceptedFiles, rejectedFiles) => {
        handleRejectedFiles(rejectedFiles);
        setFile(acceptedFiles[0] ?? null);
      },
    });

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && busy) return;
    if (!nextOpen) reset();
    onOpenChange(nextOpen);
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
    if (!effectiveProjectId) {
      notify("Vui lòng chọn dự án trước khi tải lên.", { type: "warning" });
      return;
    }
    setBusy(true);
    setValidationErrors([]);
    try {
      await uploadKnowledgeFile(payload, effectiveProjectId);
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
      const errors = (err as Error & { validationErrors?: string[] }).validationErrors ?? [];
      setValidationErrors(errors);
      notify(`Tải lên thất bại: ${(err as Error).message.split("\n")[0]}`, { type: "error" });
    } finally {
      setBusy(false);
    }
  };

  const downloadTemplate = async (kind: "knowledge" | "faq" = "knowledge") => {
    try {
      await saveKnowledgeTemplate(kind);
    } catch (err) {
      notify(`Không tải được mẫu: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-6 py-5 pr-12">
          <DialogTitle>Tải kiến thức</DialogTitle>
          <DialogDescription>
            Tải nguồn Markdown/TXT theo mẫu VFIC, mẫu FAQ hoặc Word DOCX để
            agent truy xuất trong hội thoại.
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 p-3">
            <p className="text-sm text-muted-foreground">
              FAQ dùng cùng luồng tải lên này: tải mẫu FAQ, điền câu hỏi/trả
              lời, chọn dự án rồi tải tệp Markdown lên.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => downloadTemplate("knowledge")}
              >
                <Download className="size-4" />
                Tải mẫu KB
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => downloadTemplate("faq")}
              >
                <Download className="size-4" />
                Tải mẫu FAQ
              </Button>
            </div>
          </div>

          {!lockProject && (
            <div className="grid gap-2 sm:grid-cols-[180px_1fr] sm:items-center">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Dự án
              </label>
              <Select value={effectiveProjectId} onValueChange={setProjectId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Chọn dự án" />
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

          <Tabs
            value={mode}
            onValueChange={(value) => setMode(value as "file" | "paste")}
            className="gap-4"
          >
            <div className="w-full overflow-x-auto">
              <TabsList className="grid h-10 w-full grid-cols-2">
                <TabsTrigger value="file" className="gap-2">
                  <UploadCloud className="size-4" />
                  Tải tệp
                </TabsTrigger>
                <TabsTrigger value="paste" className="gap-2">
                  <ClipboardList className="size-4" />
                  Dán văn bản
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="file" className="mt-0">
              <div
                {...getRootProps({
                  className: cn(
                    "group flex min-h-56 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed bg-muted/30 px-6 py-8 text-center transition-colors outline-none",
                    "hover:border-primary/50 hover:bg-primary/5 focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
                    isDragActive && "border-primary bg-primary/10",
                    isDragReject && "border-destructive bg-destructive/10",
                    busy && "pointer-events-none opacity-70",
                  ),
                })}
              >
                <input {...getInputProps()} />
                <span className="mb-4 flex size-14 items-center justify-center rounded-full bg-background text-primary shadow-xs ring-1 ring-border transition-transform group-hover:scale-105">
                  <UploadCloud className="size-6" />
                </span>
                <p className="text-base font-semibold">
                  {isDragActive ? "Thả tệp vào đây" : "Kéo thả tệp vào đây"}
                </p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  hoặc bấm để chọn tệp Markdown, TXT hoặc Word DOCX.
                </p>
                <p className="mt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Một tệp mỗi lần tải
                </p>
              </div>

              {file && (
                <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border bg-background p-3 shadow-xs">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <FileText className="size-5" />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {file.name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {formatFileSize(file.size)}
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8 shrink-0"
                    onClick={() => setFile(null)}
                    disabled={busy}
                    aria-label="Xóa tệp đã chọn"
                  >
                    <X className="size-4" />
                  </Button>
                </div>
              )}
            </TabsContent>

            <TabsContent value="paste" className="mt-0">
              <div className="flex flex-col gap-2">
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Nội dung tin tuyển dụng
                </label>
                <Textarea
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  rows={10}
                  placeholder="Dán toàn bộ nội dung tin tuyển dụng vào đây..."
                  className="max-h-[40vh] min-h-52 resize-y overflow-y-auto text-sm"
                />
              </div>
            </TabsContent>
          </Tabs>

          {validationErrors.length > 0 && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
              <p className="font-medium">Tệp chưa đúng định dạng:</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {validationErrors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="rounded-lg border bg-muted/30 p-3">
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-background text-muted-foreground ring-1 ring-border">
                {busy ? (
                  <RefreshCw className="size-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="size-4" />
                )}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {busy
                    ? "Đang gửi vào pipeline ingest"
                    : "Pipeline tự chạy sau khi tải lên"}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Nhận tệp, trích văn bản, tạo digest, nhúng vector và xuất bản
                  nguồn có trích dẫn cho agent truy xuất.
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
        </div>
        <DialogFooter className="shrink-0 border-t bg-background px-6 py-4">
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={busy}
          >
            Hủy
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
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
      done
        ? "bg-background text-foreground shadow-xs"
        : "bg-background/60 text-muted-foreground",
    )}
  >
    <span
      className={cn(
        "flex size-6 shrink-0 items-center justify-center rounded-md",
        done ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
      )}
    >
      {icon}
    </span>
    <span className="truncate font-medium">{label}</span>
  </div>
);
