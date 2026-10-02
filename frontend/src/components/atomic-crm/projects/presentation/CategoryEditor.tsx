import type { Ref } from "react";
import { Save, Pencil } from "lucide-react";
import { useTranslate } from "ra-core";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { CategoryDraft } from "./use-category-draft";
import type { KnowledgeCategoryStatus } from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import { PROJECT_KNOWLEDGE_CATEGORY_LABELS } from "../domain/project-knowledge-policy";
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
                : processing
                  ? `Phiên bản mới đang được kiểm tra · ${filename}`
                  : hasCurrentSource
                    ? `Dữ liệu hiện tại chatbot đang sử dụng · ${filename}`
                    : "Danh mục này chưa có dữ liệu đang dùng. Nhập tệp văn bản của dự án để hệ thống phân loại nội dung."}
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
      {canManageSources && !isEditing && (
        <div className="project-category-source-link">
          <ExternalSourceLinkForm
            projectId={projectId}
            defaultCategory={selectedKey}
            onCreated={onSourceCreated}
          />
        </div>
      )}
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
      ) : hasCurrentSource ? (
        <div className="project-category-source-content">
          <Textarea
            value={content}
            readOnly
            rows={14}
            className="project-category-textarea font-mono"
            aria-label={`Dữ liệu hiện tại của danh mục ${label}`}
            placeholder="Danh mục này chưa có dữ liệu đang dùng."
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
