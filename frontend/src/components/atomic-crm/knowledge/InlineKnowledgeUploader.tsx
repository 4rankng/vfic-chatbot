import { useState } from "react";
import { useNotify, useRefresh, useTranslate } from "ra-core";
import { useDropzone, type FileRejection } from "react-dropzone";
import {
  BookOpen,
  Download,
  FileText,
  RefreshCw,
  Upload,
  UploadCloud,
  X,
} from "lucide-react";
import { Button } from "@/components/base/buttons/button";
import { cn } from "@/lib/utils";
import {
  saveKnowledgeTemplate,
  createAndIngestKnowledgeBaseVersion,
} from "./knowledge-service";
import {
  ACCEPTED_KNOWLEDGE_TYPES,
  formatFileSize,
} from "./knowledgeUploadConfig";
import { ProjectPicker } from "./ProjectPicker";
export const InlineKnowledgeUploader = () => {
  const notify = useNotify();
  const refresh = useRefresh();
  const translate = useTranslate();
  const [projectChoice, setProjectChoice] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  const handleRejectedFiles = (rejections: FileRejection[]) => {
    if (rejections.length === 0) return;
    notify("Tệp không hợp lệ. Chỉ hỗ trợ .md, .txt hoặc .docx.", {
      type: "warning",
    });
  };

  const { getRootProps, getInputProps, isDragActive, isDragReject, open } =
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
    setValidationErrors([]);
    try {
      await createAndIngestKnowledgeBaseVersion(projectChoice, file);
      notify("Đã tạo phiên bản KB. Hãy xem lại rồi xuất bản khi sẵn sàng.", {
        type: "success",
      });
      setFile(null);
      refresh();
    } catch (err) {
      const errors =
        (err as Error & { validationErrors?: string[] }).validationErrors ?? [];
      setValidationErrors(errors);
      notify(`Tải lên thất bại: ${(err as Error).message.split("\n")[0]}`, {
        type: "error",
      });
    } finally {
      setBusy(false);
    }
  };

  const downloadTemplate = async (kind: "knowledge" | "faq" = "knowledge") => {
    try {
      await saveKnowledgeTemplate(kind);
    } catch (err) {
      notify(`Không tải được mẫu: ${(err as Error).message}`, {
        type: "error",
      });
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
            <h4 className="text-subsection font-semibold leading-6 text-foreground">
              Bắt đầu bằng một nguồn kiến thức
            </h4>
            <p className="mt-1 max-w-[34rem] text-body leading-6 text-muted-foreground">
              Gắn tệp Markdown/TXT theo mẫu, FAQ hoặc Word DOCX vào dự án để
              agent truy xuất sau khi pipeline xử lý xong.
            </p>
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-5">
        <div className="grid gap-2">
          <label className="kb-mono text-caption font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            1. Dự án
          </label>
          <ProjectPicker value={projectChoice} onChange={setProjectChoice} />
        </div>

        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-3">
            <label className="kb-mono text-caption font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              2. Tệp nguồn
            </label>
            <span className="hidden text-helper text-muted-foreground sm:inline">
              Markdown, TXT hoặc DOCX
            </span>
          </div>
          <div
            {...getRootProps({
              className: cn(
                "uu-scope group grid min-h-36 cursor-pointer place-items-center rounded-xl border border-dashed border-primary bg-primary px-5 py-6 text-center transition-colors outline-none",
                "hover:border-brand hover:bg-primary_hover focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
                isDragActive && "border-brand bg-brand-primary_alt",
                isDragReject && "border-error_subtle bg-error-primary",
                busy && "pointer-events-none opacity-70",
              ),
              role: "button",
              tabIndex: busy ? -1 : 0,
              "aria-label": "Kéo thả hoặc chọn tệp kiến thức để tải lên",
              "aria-disabled": busy || undefined,
            })}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                open();
              }
            }}
          >
            <input {...getInputProps()} />
            <div className="flex max-w-[28rem] flex-col items-center">
              <span className="flex size-12 items-center justify-center rounded-lg bg-secondary text-fg-brand-secondary ring-1 ring-secondary_alt">
                <UploadCloud className="size-5" />
              </span>
              <p className="mt-3 text-body-sm font-semibold text-primary">
                {isDragActive
                  ? "Thả tệp vào đây"
                  : "Kéo thả hoặc bấm để chọn tệp"}
              </p>
              <p className="mt-1 text-sm leading-5 text-tertiary sm:hidden">
                Tệp Markdown, TXT hoặc Word DOCX.
              </p>
            </div>
          </div>
        </div>

        {validationErrors.length > 0 && (
          <div className="tt-alert tt-alert-error tt-alert-soft rounded-[10px] border border-destructive/30 bg-destructive/10 p-3 text-body text-destructive">
            <p className="font-medium">Tệp chưa đúng định dạng:</p>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {validationErrors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="grid gap-3 border-t border-border pt-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
          {file ? (
            <div className="flex min-w-0 items-center gap-3 rounded-[10px] bg-[var(--kb-teal-soft)] px-3 py-2.5 text-[var(--kb-teal)]">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-card/80">
                <FileText className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-row-title font-semibold text-foreground">
                  {file.name}
                </p>
                <p className="kb-mono mt-0.5 text-caption text-[var(--kb-teal)]">
                  {formatFileSize(file.size)}
                </p>
              </div>
              <Button
                type="button"
                color="tertiary"
                size="sm"
                data-slot="button"
                className="uu-scope size-10 shrink-0 rounded-[9px] text-[var(--kb-teal)] hover:bg-card/70 hover:text-foreground"
                onClick={() => setFile(null)}
                isDisabled={busy}
                iconLeading={X}
                aria-label="Xóa tệp đã chọn"
              />
            </div>
          ) : (
            <p className="text-helper leading-5 text-muted-foreground">
              Chọn dự án và một tệp nguồn để bật nút tải lên.
            </p>
          )}

          {/* One action group, not three grid cells: as trailing grid items a
              wrapped button stretched to the whole status column. */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              color="secondary"
              size="md"
              data-slot="button"
              onClick={() => downloadTemplate("knowledge")}
              iconLeading={Download}
              className="uu-scope h-10 w-full rounded-[9px] px-4 [--ring-color-primary:var(--border)] sm:w-auto"
            >
              Tải mẫu KB
            </Button>
            <Button
              type="button"
              color="secondary"
              size="md"
              data-slot="button"
              onClick={() => downloadTemplate("faq")}
              iconLeading={Download}
              className="uu-scope h-10 w-full rounded-[9px] px-4 [--ring-color-primary:var(--border)] sm:w-auto"
            >
              Tải mẫu FAQ
            </Button>
            <Button
              type="button"
              size="md"
              data-slot="button"
              onClick={submit}
              isDisabled={!file || !projectChoice || busy}
              iconLeading={
                busy ? (
                  <RefreshCw className="size-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Upload className="size-4" />
                )
              }
              className="uu-scope h-10 w-full rounded-[9px] px-4 sm:w-auto"
            >
              {busy
                ? translate("crm.common.uploading")
                : translate("crm.common.upload")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
