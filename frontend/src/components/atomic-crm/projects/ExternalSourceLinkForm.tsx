import { useEffect, useId, useRef, useState } from "react";
import { useNotify } from "ra-core";
import { AlertCircle, FileText, Link2, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  createSinglePageExternalSource,
  createExternalSource,
  isValidGoogleSheetUrl,
  resolveGoogleSheetGid,
  singlePageSyncErrorMessage,
  type KnowledgeCategoryKey,
} from "./project-knowledge-service";
import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  PROJECT_KNOWLEDGE_CATEGORY_LABELS,
} from "./domain/project-knowledge-policy";

// Card: the category labels live in the domain policy so the brief import
// summary and this picker can never drift apart.
const CATEGORY_OPTIONS: { value: KnowledgeCategoryKey; label: string }[] = (
  PROJECT_KNOWLEDGE_CATEGORIES as readonly KnowledgeCategoryKey[]
).map((value) => ({ value, label: PROJECT_KNOWLEDGE_CATEGORY_LABELS[value] }));

type Props = {
  projectId: string;
  defaultCategory?: KnowledgeCategoryKey;
  onCreated?: () => void;
  disabled?: boolean;
  variant?: "category" | "single-page";
};

/**
 * Paste a public Google Sheet URL to import a knowledge category — a sibling
 * of the YAML file upload. The admin can import once or enable daily auto-sync.
 * v1 ships a parser for FAQ only; other categories will record a clear
 * "no parser" failure until their parser is added.
 */
export const ExternalSourceLinkForm = ({
  projectId,
  defaultCategory = "faq",
  onCreated,
  disabled = false,
  variant = "category",
}: Props) => {
  const notify = useNotify();
  const formId = useId();
  const sourceId = (field: string) => `${formId}-${field}`;
  const [open, setOpen] = useState(false);
  const [sheetUrl, setSheetUrl] = useState("");
  const [categoryKey, setCategoryKey] =
    useState<KnowledgeCategoryKey>(defaultCategory);
  const [autoSync, setAutoSync] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const isSinglePage = variant === "single-page";
  const contextRef = useRef(0);
  const submittingRef = useRef(false);

  useEffect(() => {
    setOpen(false);
    setSheetUrl("");
    setCategoryKey(defaultCategory);
    setAutoSync(false);
    setSubmitting(false);
    submittingRef.current = false;
    return () => {
      contextRef.current += 1;
    };
  }, [defaultCategory, projectId, variant]);

  const urlValid = sheetUrl.trim() === "" || isValidGoogleSheetUrl(sheetUrl);
  const gidResolution = sheetUrl.trim()
    ? resolveGoogleSheetGid(sheetUrl)
    : null;
  const gidValid = !sheetUrl.trim() || gidResolution?.ok;
  const gidHint = gidResolution?.ok
    ? `Sẽ đồng bộ đúng tab gid=${gidResolution.gid} từ ${
        gidResolution.source === "fragment" ? "phần #gid" : "tham số ?gid"
      } của link.`
    : (gidResolution?.message ?? null);

  const reset = () => {
    setSheetUrl("");
    setCategoryKey(defaultCategory);
    setAutoSync(false);
  };

  const submit = async () => {
    if (disabled || submittingRef.current) return;
    if (!sheetUrl.trim()) {
      notify("Vui lòng dán link Google Sheet.", { type: "warning" });
      return;
    }
    if (!isValidGoogleSheetUrl(sheetUrl)) {
      notify(
        "Link phải là Google Sheet công khai (https://docs.google.com/...).",
        {
          type: "warning",
        },
      );
      return;
    }
    if (!gidResolution?.ok) {
      notify(
        gidResolution?.message ??
          "Link cần có gid rõ ràng để chọn đúng trang tính.",
        { type: "warning" },
      );
      return;
    }
    const context = contextRef.current;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      if (isSinglePage) {
        await createSinglePageExternalSource(projectId, {
          sheet_url: sheetUrl.trim(),
          auto_sync_enabled: autoSync,
        });
      } else {
        await createExternalSource(projectId, {
          category_key: categoryKey,
          sheet_url: sheetUrl.trim(),
          sheet_gid: gidResolution.gid,
          auto_sync_enabled: autoSync,
        });
      }
      if (context !== contextRef.current) return;
      notify(
        autoSync
          ? "Đã thêm nguồn và bật đồng bộ tự động. Đang nhập nội dung lần đầu."
          : "Đã thêm nguồn. Đang nhập nội dung ngay bây giờ.",
        { type: "success" },
      );
      reset();
      setOpen(false);
      onCreated?.();
    } catch (error) {
      if (context !== contextRef.current) return;
      notify(
        isSinglePage
          ? singlePageSyncErrorMessage(error)
          : (error as Error).message,
        { type: "error" },
      );
    } finally {
      if (context === contextRef.current) {
        submittingRef.current = false;
        setSubmitting(false);
      }
    }
  };

  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={disabled}
      >
        <Link2 className="size-4" />
        Liên kết Google Sheet
      </Button>
    );
  }

  return (
    <div className="project-source-link-form">
      {/* Header */}
      <div className="project-source-link-header">
        <FileText className="size-4 text-primary" aria-hidden="true" />
        <h4 className="text-body font-semibold">
          {isSinglePage ? "Google Sheet 1 trang" : "Liên kết Google Sheet"}
        </h4>
      </div>

      {/* Body */}
      <div className="project-source-link-body">
        <div className="space-y-2">
          <Label htmlFor={sourceId("ext-src-url")}>Link Google Sheet</Label>
          <Input
            id={sourceId("ext-src-url")}
            value={sheetUrl}
            onChange={(event) => setSheetUrl(event.target.value)}
            placeholder="https://docs.google.com/spreadsheets/d/.../edit#gid=123456789"
            inputMode="url"
            autoComplete="off"
            aria-invalid={!urlValid || !gidValid}
            aria-describedby={
              !urlValid
                ? sourceId("ext-src-url-error")
                : !gidValid
                  ? sourceId("ext-src-gid-error")
                  : gidResolution?.ok
                    ? sourceId("ext-src-gid-preview")
                    : undefined
            }
            disabled={submitting || disabled}
          />
          {!urlValid && (
            <p
              id={sourceId("ext-src-url-error")}
              className="text-body-sm text-destructive"
            >
              Chỉ nhận link https://docs.google.com/... (Sheet đặt "Anyone with
              link can view").
            </p>
          )}
          {urlValid && gidHint && (
            <p
              id={
                gidResolution?.ok
                  ? sourceId("ext-src-gid-preview")
                  : sourceId("ext-src-gid-error")
              }
              className={
                gidResolution?.ok
                  ? "text-body-sm text-muted-foreground"
                  : "text-body-sm text-destructive"
              }
            >
              {gidHint}
            </p>
          )}
        </div>

        {!isSinglePage && (
          <div className="space-y-1.5">
            <Label htmlFor={sourceId("ext-src-category")}>Danh mục</Label>
            <Select
              value={categoryKey}
              onValueChange={(value) =>
                setCategoryKey(value as KnowledgeCategoryKey)
              }
              disabled={submitting || disabled}
            >
              <SelectTrigger id={sourceId("ext-src-category")} className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <label
          htmlFor={sourceId("ext-src-autosync")}
          className="flex items-start justify-between gap-3 rounded-md border border-border bg-muted/20 p-3 transition-colors hover:bg-muted/40"
        >
          <span className="space-y-0.5">
            <span className="block text-body font-medium">
              Đồng bộ tự động hàng ngày
            </span>
            <span className="block text-body-sm text-muted-foreground">
              {isSinglePage
                ? "Tự làm mới trang kiến thức khi Google Sheet thay đổi."
                : "Ghi đè nội dung hiện tại khi Sheet thay đổi."}
            </span>
          </span>
          <Switch
            id={sourceId("ext-src-autosync")}
            checked={autoSync}
            onCheckedChange={setAutoSync}
            disabled={submitting || disabled}
            aria-label="Bật đồng bộ tự động hàng ngày"
          />
        </label>
        {isSinglePage && autoSync && (
          <Alert variant="warning">
            <AlertCircle aria-hidden="true" />
            <AlertTitle>Đồng bộ tự động có thể ghi đè chỉnh sửa tay</AlertTitle>
            <AlertDescription>
              Khi bật lịch hàng ngày, nội dung trong Google Sheet sẽ thay thế
              nội dung trang kiến thức ở lần đồng bộ tiếp theo.
            </AlertDescription>
          </Alert>
        )}
      </div>

      {/* Footer */}
      <div className="project-source-link-footer">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setOpen(false)}
          disabled={submitting || disabled}
        >
          Hủy
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={() => void submit()}
          disabled={submitting || disabled || !urlValid || !gidValid}
        >
          {submitting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Link2 className="size-4" />
          )}
          {autoSync ? "Thêm & bật đồng bộ" : "Nhập một lần"}
        </Button>
      </div>
    </div>
  );
};
