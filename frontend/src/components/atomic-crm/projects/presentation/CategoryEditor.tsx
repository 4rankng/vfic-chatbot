import type { Ref } from "react";
import { Save, Pencil, Download } from "lucide-react";
import { useTranslate } from "ra-core";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { CategoryDraft } from "./use-category-draft";
import type { KnowledgeCategoryStatus } from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import { ExternalSourceLinkForm } from "../ExternalSourceLinkForm";

type Props = {
  ref?: Ref<HTMLElement>;
  projectId: string;
  /** Selected key, used as the label fallback until the catalog lands. */
  selectedKey: ProjectKnowledgeCategory;
  category?: KnowledgeCategoryStatus;
  draft: CategoryDraft;
  /** The selected category has a revision under review. */
  processing: boolean;
  editable: boolean;
  canManageSources: boolean;
  onSourceCreated: () => void;
};

/** Detail pane of the selected knowledge category: review state, actions, the
 *  category's markdown source. */
export const CategoryEditor = ({
  ref,
  projectId,
  selectedKey,
  category,
  draft,
  processing,
  editable,
  canManageSources,
  onSourceCreated,
}: Props) => {
  const translate = useTranslate();
  const label = category?.label_vi ?? selectedKey;
  const {
    cancelEditing,
    content,
    downloadTemplate,
    filename,
    hasCurrentSource,
    hasUnsavedChanges,
    isEditing,
    loading,
    save,
    saving,
    setContent,
    startEditing,
    template,
  } = draft;

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
            {!loading && (
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
            {isEditing
              ? "Chỉnh sửa nội dung trực tiếp, sau đó lưu để hệ thống kiểm tra."
              : processing
                ? `Phiên bản mới đang được kiểm tra · ${filename}`
                : hasCurrentSource
                  ? `Dữ liệu hiện tại Agent đang sử dụng · ${filename}`
                  : "Danh mục này chưa có dữ liệu đang dùng. Tải mẫu để chuẩn bị nội dung mới."}
          </p>
        </div>
        <div className="project-category-editor-actions">
          {editable && !isEditing && (
            <Button
              size="sm"
              className="tt-btn-touch"
              onClick={startEditing}
              disabled={saving || loading || processing}
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
                disabled={saving || !hasUnsavedChanges}
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
          <Button
            variant="outline"
            size="sm"
            className="tt-btn-touch"
            onClick={downloadTemplate}
            disabled={!template || loading}
          >
            <Download className="size-4" /> Tải mẫu
          </Button>
          {canManageSources && !isEditing && (
            <ExternalSourceLinkForm
              projectId={projectId}
              defaultCategory={selectedKey}
              onCreated={onSourceCreated}
            />
          )}
        </div>
      </div>
      {loading ? (
        <Skeleton className="project-category-editor-skeleton" />
      ) : isEditing ? (
        <Textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={20}
          className="project-category-textarea border-primary font-mono ring-3 ring-primary/10"
          aria-label={`Dữ liệu hiện tại của danh mục ${label}`}
          placeholder="Danh mục này chưa có dữ liệu. Hãy tải mẫu hoặc sửa nội dung trực tiếp."
        />
      ) : hasCurrentSource ? (
        <div className="border-y border-border py-2">
          <Textarea
            value={content}
            readOnly
            rows={14}
            className="project-category-textarea font-mono"
            aria-label={`Dữ liệu hiện tại của danh mục ${label}`}
            placeholder="Danh mục này chưa có dữ liệu. Hãy tải mẫu hoặc sửa nội dung trực tiếp."
          />
        </div>
      ) : null}
    </section>
  );
};
