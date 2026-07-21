import { useState } from "react";
import { useNotify } from "ra-core";
import { Link2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
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
  const [sheetGid, setSheetGid] = useState("0");
  const [categoryKey, setCategoryKey] =
    useState<KnowledgeCategoryKey>(defaultCategory);
  const [autoSync, setAutoSync] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const urlValid = sheetUrl.trim() === "" || isValidGoogleSheetUrl(sheetUrl);

  const reset = () => {
    setSheetUrl("");
    setSheetGid("0");
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
        sheet_gid: Number(sheetGid) || 0,
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
        Nhập từ link công khai
      </Button>
    );
  }

  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-body font-semibold">Nhập từ link Google Sheet công khai</h4>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setOpen(false)}
          disabled={submitting}
        >
          Hủy
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
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
          <Label htmlFor="ext-src-category">Danh mục đích</Label>
          <select
            id="ext-src-category"
            value={categoryKey}
            onChange={(event) =>
              setCategoryKey(event.target.value as KnowledgeCategoryKey)
            }
            disabled={submitting}
            className={cn(
              "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1",
              "text-body shadow-sm transition-colors focus-visible:outline-none",
              "focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed",
              "disabled:opacity-50",
            )}
          >
            {CATEGORY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ext-src-gid">ID trang (gid, nâng cao)</Label>
          <Input
            id="ext-src-gid"
            value={sheetGid}
            onChange={(event) => setSheetGid(event.target.value)}
            inputMode="numeric"
            disabled={submitting}
          />
        </div>
      </div>
      <label className="flex items-center gap-2 text-body">
        <input
          type="checkbox"
          checked={autoSync}
          onChange={(event) => setAutoSync(event.target.checked)}
          disabled={submitting}
          className="size-4"
        />
        Bật đồng bộ tự động hàng ngày (ghi đè nội dung hiện tại khi Sheet thay đổi)
      </label>
      <div className="flex justify-end">
        <Button type="button" onClick={() => void submit()} disabled={submitting}>
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
