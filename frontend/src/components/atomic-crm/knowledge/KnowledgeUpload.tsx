import { useEffect, useState } from "react";
import { useNotify, useRefresh, useTranslate } from "ra-core";
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
  Modal,
  ModalOverlay,
} from "@/components/application/modals/modal";
import { Button } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import {
  ButtonGroup,
  ButtonGroupItem,
} from "@/components/base/button-group/button-group";
import { TextArea } from "@/components/base/textarea/textarea";
import {
  saveKnowledgeTemplate,
  createAndIngestKnowledgeBaseVersion,
} from "./knowledge-service";
import { cn } from "@/lib/utils";
import {
  ACCEPTED_KNOWLEDGE_TYPES,
  formatFileSize,
} from "./knowledgeUploadConfig";
import { ProjectPicker } from "./ProjectPicker";

interface KnowledgeUploadProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-select a project (used when opening from the Project editor). */
  initialProjectId?: string;
  /** Hide the project selector — upload is bound to initialProjectId. */
  lockProject?: boolean;
}

// Every KB upload is staged in a project-scoped release. Paste becomes a text
// file so it follows the same reviewed release path as uploaded files.
export const KnowledgeUpload = ({
  open,
  onOpenChange,
  initialProjectId,
  lockProject = false,
}: KnowledgeUploadProps) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const translate = useTranslate();
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

  const {
    getRootProps,
    getInputProps,
    isDragActive,
    isDragReject,
    open: openFilePicker,
  } = useDropzone({
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
          ? new File([pasteText], "kien-thuc.txt", { type: "text/plain" })
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
      await createAndIngestKnowledgeBaseVersion(effectiveProjectId, payload);
      notify(
        "Đã tạo phiên bản KB và đưa vào hàng đợi. Hãy xem lại rồi xuất bản khi sẵn sàng.",
        {
          type: "success",
        },
      );
      reset();
      onOpenChange(false);
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
    <ModalOverlay
      isOpen={open}
      onOpenChange={handleOpenChange}
      isDismissable
      isKeyboardDismissDisabled={busy}
      className="uu-scope"
    >
      <Modal className="w-full outline-hidden sm:max-w-2xl">
        <Dialog
          aria-label="Tải kiến thức"
          className="flex max-h-[90vh] flex-col items-stretch gap-0 overflow-hidden p-0 outline-hidden"
        >
          <header className="relative border-b border-secondary px-6 py-5 pr-12">
            <h2 className="text-lg font-semibold text-primary">
              Tải kiến thức
            </h2>
            <p className="mt-1 text-sm text-tertiary">
              Tải KB, FAQ hoặc DOCX cho dự án.
            </p>
            <CloseButton
              size="sm"
              label={translate("ra.action.close")}
              isDisabled={busy}
              className="absolute top-4 right-4"
            />
          </header>
          <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 px-3 py-2.5">
              <span className="text-label font-medium text-muted-foreground">
                Mẫu
              </span>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  color="secondary"
                  size="sm"
                  data-slot="button"
                  onClick={() => downloadTemplate("knowledge")}
                  iconLeading={Download}
                  className="uu-scope [--ring-color-primary:var(--border)]"
                >
                  Tải mẫu KB
                </Button>
                <Button
                  type="button"
                  color="secondary"
                  size="sm"
                  data-slot="button"
                  onClick={() => downloadTemplate("faq")}
                  iconLeading={Download}
                  className="uu-scope [--ring-color-primary:var(--border)]"
                >
                  Tải mẫu FAQ
                </Button>
              </div>
            </div>

            {!lockProject && (
              <div className="grid gap-2 sm:grid-cols-[180px_1fr] sm:items-center">
                <label className="text-helper font-medium uppercase tracking-wide text-muted-foreground">
                  Dự án
                </label>
                <ProjectPicker
                  value={effectiveProjectId}
                  onChange={setProjectId}
                />
              </div>
            )}

            <div className="tt-alert tt-alert-info tt-alert-soft rounded-lg border bg-muted/20 p-3">
              <div>
                <p className="text-body font-medium">
                  Phiên bản KB có kiểm soát
                </p>
                <p className="mt-1 text-helper text-muted-foreground">
                  Mỗi tệp tạo một phiên bản KB riêng và cần được xem lại trước
                  khi xuất bản.
                </p>
              </div>
            </div>

            <ButtonGroup
              size="sm"
              className="uu-scope w-full"
              aria-label="Chế độ tải kiến thức"
              selectedKeys={[mode]}
              onSelectionChange={(keys) => {
                const next = [...keys][0];
                if (next) setMode(next as "file" | "paste");
              }}
            >
              <ButtonGroupItem
                id="file"
                iconLeading={UploadCloud}
                className="flex-1 justify-center"
              >
                Tải tệp
              </ButtonGroupItem>
              <ButtonGroupItem
                id="paste"
                iconLeading={ClipboardList}
                className="flex-1 justify-center"
              >
                Dán văn bản
              </ButtonGroupItem>
            </ButtonGroup>

            {mode === "file" ? (
              <>
                <div
                  {...getRootProps({
                    className: cn(
                      "uu-scope group flex min-h-56 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-primary bg-primary px-6 py-8 text-center transition-colors outline-none",
                      "hover:border-brand hover:bg-primary_hover focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
                      isDragActive && "border-brand bg-brand-primary_alt",
                      isDragReject && "border-error_subtle bg-error-primary",
                      busy && "pointer-events-none opacity-70",
                    ),
                    role: "button",
                    tabIndex: busy ? -1 : 0,
                    "aria-label": "Kéo thả hoặc chọn tệp để tải lên",
                    "aria-disabled": busy || undefined,
                  })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      openFilePicker();
                    }
                  }}
                >
                  <input {...getInputProps()} />
                  <span className="mb-4 flex size-14 items-center justify-center rounded-full bg-secondary text-fg-brand-secondary ring-1 ring-secondary_alt">
                    <UploadCloud className="size-6" />
                  </span>
                  <p className="text-section-title font-semibold text-primary">
                    {isDragActive ? "Thả tệp vào đây" : "Kéo thả tệp vào đây"}
                  </p>
                  <p className="mt-1 max-w-sm text-body-sm text-tertiary">
                    hoặc bấm để chọn tệp Markdown, TXT hoặc Word DOCX.
                  </p>
                  <p className="mt-4 text-xs font-medium tracking-wide text-quaternary uppercase">
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
                        <p className="truncate text-row-title font-medium">
                          {file.name}
                        </p>
                        <p className="text-helper text-muted-foreground">
                          {formatFileSize(file.size)}
                        </p>
                      </div>
                    </div>
                    <Button
                      type="button"
                      color="tertiary"
                      size="sm"
                      data-slot="button"
                      className="uu-scope size-10 shrink-0"
                      onClick={() => setFile(null)}
                      isDisabled={busy}
                      iconLeading={X}
                      aria-label="Xóa tệp đã chọn"
                    />
                  </div>
                )}
              </>
            ) : null}

            {mode === "paste" ? (
              <TextArea
                label="Nội dung kiến thức"
                className="uu-scope"
                value={pasteText}
                onChange={setPasteText}
                rows={10}
                placeholder="Dán nội dung mà chatbot cần tham khảo vào đây..."
                textAreaClassName="max-h-[40vh] min-h-52 resize-y overflow-y-auto text-control"
              />
            ) : null}

            {validationErrors.length > 0 && (
              <div className="tt-alert tt-alert-error tt-alert-soft rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-body text-destructive">
                <p className="font-medium">Tệp chưa đúng định dạng:</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {validationErrors.map((error) => (
                    <li key={error}>{error}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="tt-alert tt-alert-info tt-alert-soft rounded-lg border bg-muted/30 p-3">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-background text-muted-foreground ring-1 ring-border">
                  {busy ? (
                    <RefreshCw className="size-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="size-4" />
                  )}
                </span>
                <div className="min-w-0">
                  <p className="text-body font-medium">
                    {busy
                      ? "Đang gửi vào pipeline ingest"
                      : "Pipeline tự chạy sau khi tải lên"}
                  </p>
                  <p className="mt-1 text-helper leading-5 text-muted-foreground">
                    Nhận tệp, trích văn bản, tạo digest, nhúng vector và xuất
                    bản nguồn có trích dẫn cho agent truy xuất.
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
          <footer className="flex shrink-0 flex-col-reverse items-stretch gap-3 border-t border-secondary bg-background px-6 py-4 sm:flex-row sm:items-center sm:justify-end">
            <Button
              type="button"
              color="secondary"
              size="md"
              data-slot="button"
              className="uu-scope"
              isDisabled={busy}
              onClick={() => handleOpenChange(false)}
            >
              {translate("ra.action.cancel")}
            </Button>
            <Button
              type="button"
              size="md"
              data-slot="button"
              className="uu-scope"
              onClick={submit}
              isDisabled={!canSubmit}
              iconLeading={
                busy ? (
                  <RefreshCw className="size-4 animate-spin motion-reduce:animate-none" />
                ) : undefined
              }
            >
              {busy
                ? translate("crm.common.uploading")
                : translate("crm.common.upload")}
            </Button>
          </footer>
        </Dialog>
      </Modal>
    </ModalOverlay>
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
      "flex min-w-0 items-center gap-2 rounded-lg px-2 py-2 text-helper",
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
