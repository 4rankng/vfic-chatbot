import { useState } from "react";
import { useNotify } from "ra-core";
import { FileText, Link2, Loader2 } from "lucide-react";
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
  createExternalSource,
  isValidGoogleSheetUrl,
  type KnowledgeCategoryKey,
} from "@/lib/vfic/knowledgeService";

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
}: Props) => {
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const [sheetUrl, setSheetUrl] = useState("");
  const [categoryKey, setCategoryKey] =
    useState<KnowledgeCategoryKey>(defaultCategory);
  const [autoSync, setAutoSync] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const urlValid = sheetUrl.trim() === "" || isValidGoogleSheetUrl(sheetUrl);

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
      notify("Link phải là Google Sheet công khai (https://docs.google.com/...).", {
        type: "warning",
      });
      return;
    }
    setSubmitting(true);
    try {
      await createExternalSource(projectId, {
        category_key: categoryKey,
        sheet_url: sheetUrl.trim(),
        sheet_gid: 0,
        auto_sync_enabled: autoSync,
      });
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
      notify((error as Error).message, { type: "error" });
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
        Google Docs Link
      </Button>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card shadow-xs">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border bg-muted/30 px-4 py-3">
        <FileText className="size-4 text-primary" aria-hidden="true" />
        <h4 className="text-body font-semibold">Google Doc Link</h4>
      </div>

      {/* Body */}
      <div className="space-y-4 p-4">
        <div className="space-y-1.5">
          <Label htmlFor="ext-src-url">Link Google Sheet</Label>
          <Input
            id="ext-src-url"
            value={sheetUrl}
            onChange={(event) => setSheetUrl(event.target.value)}
            placeholder="https://docs.google.com/spreadsheets/d/..."
            inputMode="url"
            aria-invalid={!urlValid}
            aria-describedby={!urlValid ? "ext-src-url-error" : undefined}
            disabled={submitting}
          />
          {!urlValid && (
            <p id="ext-src-url-error" className="text-body-sm text-destructive">
              Chỉ nhận link https://docs.google.com/... (Sheet đặt "Anyone with
              link can view").
            </p>
          )}
        </div>

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

        <label
          htmlFor="ext-src-autosync"
          className="flex items-start justify-between gap-3 rounded-md border border-border bg-muted/20 p-3 transition-colors hover:bg-muted/40"
        >
          <span className="space-y-0.5">
            <span className="block text-body font-medium">
              Đồng bộ tự động hàng ngày
            </span>
            <span className="block text-body-sm text-muted-foreground">
              Ghi đè nội dung hiện tại khi Sheet thay đổi.
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
          disabled={submitting}
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
