import { useEffect, useState } from "react";
import { useNotify, useRefresh } from "ra-core";
import { useDropzone, type FileRejection } from "react-dropzone";
import {
  BookOpen,
  FileText,
  RefreshCw,
  Upload,
  UploadCloud,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { uploadKnowledgeFile } from "@/lib/vfic/knowledgeService";
import {
  ACCEPTED_KNOWLEDGE_TYPES,
  formatFileSize,
} from "./knowledgeUploadConfig";
import type { Project } from "../types";
import { ProjectPicker } from "./ProjectPicker";
export const InlineKnowledgeUploader = ({
  projects,
}: {
  projects: Project[];
}) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const [projectChoice, setProjectChoice] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!projectChoice && projects[0]?.id)
      setProjectChoice(String(projects[0].id));
  }, [projectChoice, projects]);

  const handleRejectedFiles = (rejections: FileRejection[]) => {
    if (rejections.length === 0) return;
    notify("Tệp không hợp lệ. Hỗ trợ PDF, DOCX, XLSX, CSV, TXT và MD.", {
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
        if (acceptedFiles[0]) setFile(acceptedFiles[0]);
      },
    });

  const submit = async () => {
    if (!file) {
      notify("Vui lòng chọn tệp trước khi tải lên.", { type: "warning" });
      return;
    }
    if (!projectChoice) {
      notify("Vui lòng chọn dự án trước khi tải lên.", { type: "warning" });
      return;
    }
    setBusy(true);
    try {
      await uploadKnowledgeFile(file, projectChoice);
      notify("Đã tải lên. Pipeline đang xử lý ở nền.", { type: "success" });
      setFile(null);
      refresh();
    } catch (err) {
      notify(`Tải lên thất bại: ${(err as Error).message}`, { type: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-[420px] flex-col px-5 py-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-[10px] bg-[var(--kb-teal-soft)] text-[var(--kb-teal)]">
            <BookOpen className="size-5" />
          </span>
          <div className="min-w-0">
            <h4 className="text-[15px] font-semibold leading-6 text-foreground">
              Bắt đầu bằng một nguồn kiến thức
            </h4>
            <p className="mt-1 max-w-[34rem] text-sm leading-6 text-muted-foreground">
              Gắn tài liệu vào dự án để agent có thể truy xuất nội dung sau khi
              pipeline xử lý xong.
            </p>
          </div>
        </div>
        <Badge
          variant="secondary"
          className="kb-mono hidden shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold sm:inline-flex"
        >
          0 nguồn
        </Badge>
      </div>

      <div className="mt-6 grid gap-5">
        <div className="grid gap-2">
          <label className="kb-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            1. Dự án
          </label>
          <ProjectPicker
            value={projectChoice}
            projects={projects}
            onChange={setProjectChoice}
          />
        </div>

        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-3">
            <label className="kb-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              2. Tệp nguồn
            </label>
            <span className="hidden text-xs text-muted-foreground sm:inline">
              PDF, DOCX, XLSX, CSV, TXT, MD
            </span>
          </div>
          <div
            {...getRootProps({
              className: cn(
                "group grid min-h-36 cursor-pointer place-items-center rounded-[12px] border border-dashed border-[var(--kb-line-strong)] bg-background/70 px-5 py-6 text-center transition-colors outline-none",
                "hover:border-[var(--kb-teal)] hover:bg-[var(--kb-teal-soft)]/55 focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
                isDragActive &&
                  "border-[var(--kb-teal)] bg-[var(--kb-teal-soft)]",
                isDragReject && "border-destructive bg-destructive/10",
                busy && "pointer-events-none opacity-70",
              ),
            })}
          >
            <input {...getInputProps()} />
            <div className="flex max-w-[28rem] flex-col items-center">
              <span className="flex size-12 items-center justify-center rounded-[10px] bg-card text-[var(--kb-teal)] shadow-[inset_0_0_0_1px_var(--border)]">
                <UploadCloud className="size-5 transition-transform group-hover:-translate-y-0.5" />
              </span>
              <p className="mt-3 text-sm font-semibold text-foreground">
                {isDragActive
                  ? "Thả tệp vào đây"
                  : "Kéo thả hoặc bấm để chọn tệp"}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground sm:hidden">
                PDF, DOCX, XLSX, CSV, TXT hoặc MD.
              </p>
            </div>
          </div>
        </div>

        <div className="grid gap-3 border-t border-border pt-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
          {file ? (
            <div className="flex min-w-0 items-center gap-3 rounded-[10px] bg-[var(--kb-teal-soft)] px-3 py-2.5 text-[var(--kb-teal)]">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-card/80">
                <FileText className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground">
                  {file.name}
                </p>
                <p className="kb-mono mt-0.5 text-[11px] text-[var(--kb-teal)]">
                  {formatFileSize(file.size)}
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8 shrink-0 rounded-[9px] text-[var(--kb-teal)] hover:bg-card/70 hover:text-foreground"
                onClick={() => setFile(null)}
                disabled={busy}
                aria-label="Xóa tệp đã chọn"
              >
                <X className="size-4" />
              </Button>
            </div>
          ) : (
            <p className="text-xs leading-5 text-muted-foreground">
              Chọn dự án và một tệp để bật nút tải lên.
            </p>
          )}

          <Button
            type="button"
            onClick={submit}
            disabled={!file || !projectChoice || busy}
            className="h-10 w-full rounded-[9px] px-4 sm:w-auto"
          >
            {busy ? (
              <RefreshCw className="size-4 animate-spin" />
            ) : (
              <Upload className="size-4" />
            )}
            {busy ? "Đang tải lên..." : "Tải lên"}
          </Button>
        </div>
      </div>
    </div>
  );
};
