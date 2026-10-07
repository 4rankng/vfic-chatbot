import { useEffect, useMemo, useState, type Ref } from "react";
import { Save, Pencil } from "lucide-react";
import { useTranslate } from "ra-core";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { parseCategoryMarkdownView } from "../domain/category-markdown-reader";
import type { CategoryDraft } from "./use-category-draft";
import type { KnowledgeCategoryStatus } from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import { PROJECT_KNOWLEDGE_CATEGORY_LABELS } from "../domain/project-knowledge-policy";
import { CategoryRecordCards } from "./CategoryRecordCards";

type Props = {
  ref?: Ref<HTMLElement>;
  /** Selected key, used as the label fallback until the catalog lands. */
  selectedKey: ProjectKnowledgeCategory;
  category?: KnowledgeCategoryStatus;
  draft: CategoryDraft;
  /** The selected category has a revision under review. "processing" drives
   *  the review-state badge and the meta line. */
  processing: boolean;
  editable: boolean;
};

/** Detail pane of the selected knowledge category: sticky review header, the
 *  category's record cards (or the raw markdown behind "Xem markdown"), and
 *  the editing flow. */
export const CategoryEditor = ({
  ref,
  selectedKey,
  category,
  draft,
  processing,
  editable,
}: Props) => {
  const translate = useTranslate();
  const label =
    category?.label_vi ?? PROJECT_KNOWLEDGE_CATEGORY_LABELS[selectedKey];
  const {
    cancelEditing,
    content,
    filename,
    hasCurrentSource,
    hasUnsavedChanges,
    isEditing,
    loading,
    loadFailed,
    reload,
    save,
    saving,
    setContent,
    startEditing,
  } = draft;
  /** Cards are the default read view; the toggle reveals the raw markdown. */
  const [rawView, setRawView] = useState(false);
  useEffect(() => {
    setRawView(false);
    // A new selection lands on the cards view.
  }, [selectedKey]);

  const meta = useMemo(() => {
    const updated = category?.updated_at
      ? new Intl.DateTimeFormat("vi-VN", {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
        }).format(new Date(category.updated_at))
      : null;
    if (processing) {
      return `Phiên bản mới đang được kiểm tra · ${filename}`;
    }
    if (hasCurrentSource) {
      return updated ? `${filename} · Cập nhật ${updated}` : filename;
    }
    return null;
  }, [category?.updated_at, filename, hasCurrentSource, processing]);

  // Parse the RAW stored content: record scalars carry escaped `\n`/`\"`
  // sequences that the reader unescapes per field. Pre-converting them to
  // real newlines here would shatter a multi-line scalar into stray lines
  // and mark most of the record malformed (LG-DISPLAY jobs, 2026-10-07).
  const view = useMemo(
    () => parseCategoryMarkdownView(content, selectedKey),
    [content, selectedKey],
  );
  const showCards =
    hasCurrentSource && !isEditing && !processing && view.records.length > 0;

  return (
    <section
      ref={ref}
      id="project-category-detail"
      className="project-category-editor"
      tabIndex={-1}
      aria-labelledby="project-category-detail-title"
      aria-busy={loading}
    >
      <div className="project-category-editor-header">
        <div className="project-category-editor-heading">
          <div className="project-category-editor-title-row">
            <h3
              id="project-category-detail-title"
              className="project-category-editor-title"
            >
              {label}
            </h3>
            {!loading && !loadFailed && (
              <Badge
                variant={
                  hasCurrentSource || processing ? "secondary" : "outline"
                }
              >
                {processing
                  ? translate("crm.common.testing")
                  : hasCurrentSource
                    ? `Đang dùng v${category?.active_revision_no ?? 1}`
                    : translate("crm.common.no_data")}
              </Badge>
            )}
          </div>
          <p className="project-category-editor-description" aria-live="polite">
            {loadFailed
              ? "Chưa đọc được dữ liệu hiện tại. Hãy thử tải lại trước khi sửa nội dung."
              : isEditing
                ? "Chỉnh sửa nội dung trực tiếp, sau đó lưu để hệ thống kiểm tra."
                : (meta ??
                  "Danh mục này chưa có dữ liệu đang dùng. Nhập tệp văn bản của dự án để hệ thống phân loại nội dung.")}
          </p>
        </div>
        <div className="project-category-editor-actions">
          {editable && !isEditing && (
            <Button
              size="sm"
              className="tt-btn-touch"
              onClick={startEditing}
              disabled={saving || loading || loadFailed || processing}
            >
              <Pencil className="size-4" />
              Sửa nội dung
            </Button>
          )}
          {editable && isEditing && (
            <>
              <Button
                variant="outline"
                size="sm"
                className="tt-btn-touch"
                onClick={cancelEditing}
                disabled={saving}
              >
                {translate("ra.action.cancel")}
              </Button>
              <Button
                size="sm"
                className={cn(
                  "project-category-save-button tt-btn-touch",
                  !hasUnsavedChanges && "text-[var(--muted-foreground)]!",
                )}
                onClick={() => void save()}
                disabled={saving || loading || loadFailed || !hasUnsavedChanges}
              >
                {saving ? (
                  <span
                    className="tt-loading tt-loading-spinner tt-loading-sm"
                    aria-hidden="true"
                  />
                ) : (
                  <Save className="size-4" />
                )}
                {translate("crm.common.save_changes")}
              </Button>
            </>
          )}
        </div>
      </div>
      {loading ? (
        <Skeleton className="project-category-editor-skeleton" />
      ) : loadFailed ? (
        <div role="alert" className="space-y-3 border-y border-border py-4">
          <p className="text-sm text-muted-foreground">
            Không thể xác nhận nguồn dữ liệu của danh mục. Nội dung bạn đang sửa
            được giữ lại; vui lòng tải lại để tiếp tục.
          </p>
          <Button
            variant="outline"
            size="sm"
            className="tt-btn-touch"
            onClick={() => void reload()}
          >
            Thử lại
          </Button>
        </div>
      ) : isEditing ? (
        <Textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={20}
          className="project-category-textarea border-primary font-mono ring-3 ring-primary/10"
          aria-label={`Dữ liệu hiện tại của danh mục ${label}`}
          placeholder="Nhập nội dung của danh mục để kiểm tra và lưu."
        />
      ) : showCards ? (
        <div className="project-category-read-surface">
          {rawView ? (
            <Textarea
              value={content.replace(/\\n/g, "\n")}
              readOnly
              rows={14}
              className="project-category-textarea font-mono"
              aria-label={`Dữ liệu hiện tại của danh mục ${label}`}
            />
          ) : (
            <CategoryRecordCards view={view} />
          )}
          <div className="project-category-read-footer">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="tt-btn-touch"
              aria-pressed={rawView}
              onClick={() => setRawView((value) => !value)}
            >
              {rawView ? "Xem thẻ" : "Xem markdown"}
            </Button>
          </div>
        </div>
      ) : hasCurrentSource ? (
        <div className="project-category-source-content">
          <Textarea
            value={content.replace(/\\n/g, "\n")}
            readOnly
            rows={14}
            className="project-category-textarea font-mono"
            aria-label={`Dữ liệu hiện tại của danh mục ${label}`}
          />
        </div>
      ) : (
        <div className="project-category-empty-state">
          <p className="text-body font-medium">Chưa có nội dung</p>
          <p className="text-helper text-muted-foreground">
            {editable
              ? "Nhập tệp thông tin dự án hoặc chọn Sửa nội dung để thêm danh mục này."
              : "Danh mục này chưa được bổ sung kiến thức."}
          </p>
        </div>
      )}
    </section>
  );
};
