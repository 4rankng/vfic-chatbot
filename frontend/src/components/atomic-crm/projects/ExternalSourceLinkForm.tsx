import { useState } from "react";
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

const CATEGORY_OPTIONS: { value: KnowledgeCategoryKey; label: string }[] = [
  { value: "faq", label: "Câu hỏi thường gặp" },
  { value: "jobs", label: "Vị trí tuyển dụng" },
  { value: "compensation", label: "Lương & thu nhập" },
  { value: "requirements", label: "Yêu cầu ứng viên" },
  { value: "work_schedules", label: "Ca làm việc" },
  { value: "benefits", label: "Phúc lợi" },
  { value: "accommodation", label: "Chỗ ở" },
  { value: "meals", label: "Bữa ăn" },
  { value: "transportation", label: "Đưa đón & lịch xe" },
  { value: "insurance", label: "Bảo hiểm" },
  { value: "application", label: "Ứng tuyển & nhận việc" },
  { value: "contacts", label: "Liên hệ" },
];

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
  const [open, setOpen] = useState(false);
  const [sheetUrl, setSheetUrl] = useState("");
  const [categoryKey, setCategoryKey] =
    useState<KnowledgeCategoryKey>(defaultCategory);
  const [autoSync, setAutoSync] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const isSinglePage = variant === "single-page";

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
      notify(
        isSinglePage
          ? singlePageSyncErrorMessage(error)
          : (error as Error).message,
        { type: "error" },
      );
    } finally {
      setSubmitting(false);
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
        {isSinglePage ? "Liên kết Google Sheet" : "Gsheet Link"}
      </Button>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card shadow-xs">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border bg-muted/30 px-4 py-3">
        <FileText className="size-4 text-primary" aria-hidden="true" />
        <h4 className="text-body font-semibold">
          {isSinglePage ? "Google Sheet 1 trang" : "Gsheet Link"}
        </h4>
      </div>

      {/* Body */}
      <div className="space-y-4 p-4">
        <div className="space-y-2">
          <Label htmlFor="ext-src-url">Link Google Sheet</Label>
          <Input
            id="ext-src-url"
            value={sheetUrl}
            onChange={(event) => setSheetUrl(event.target.value)}
            placeholder={
              isSinglePage
                ? "https://docs.google.com/spreadsheets/d/.../edit#gid=123456789"
                : "https://docs.google.com/spreadsheets/d/.../edit#gid=123456789"
            }
            inputMode="url"
            aria-invalid={!urlValid || !gidValid}
            aria-describedby={
              !urlValid
                ? "ext-src-url-error"
                : !gidValid
                  ? "ext-src-gid-error"
                  : isSinglePage && gidResolution?.ok
                    ? "ext-src-gid-preview"
                    : undefined
            }
            disabled={submitting}
          />
          {!urlValid && (
            <p id="ext-src-url-error" className="text-body-sm text-destructive">
              Chỉ nhận link https://docs.google.com/... (Sheet đặt "Anyone with
              link can view").
            </p>
          )}
          {urlValid && gidHint && (
            <p
              id={
                gidResolution?.ok ? "ext-src-gid-preview" : "ext-src-gid-error"
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
            <Label htmlFor="ext-src-category">Danh mục</Label>
            <Select
              value={categoryKey}
              onValueChange={(value) =>
                setCategoryKey(value as KnowledgeCategoryKey)
              }
              disabled={submitting}
            >
              <SelectTrigger id="ext-src-category" className="h-9">
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
          htmlFor="ext-src-autosync"
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
            id="ext-src-autosync"
            checked={autoSync}
            onCheckedChange={setAutoSync}
            disabled={submitting}
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
      <div className="flex items-center justify-end gap-2 border-t border-border bg-muted/30 px-4 py-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setOpen(false)}
          disabled={submitting}
        >
          Hủy
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={() => void submit()}
          disabled={submitting || !urlValid || !gidValid}
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
