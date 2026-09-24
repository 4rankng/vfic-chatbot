import { useRef, useState } from "react";
import { AlertCircle, ChevronRight, Database, Link2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Project } from "../types";
import { useCategoryDraft } from "./application/use-category-draft";
import { useFaqAutoSyncNotice } from "./application/use-faq-auto-sync-notice";
import { useProjectKnowledgeCatalog } from "./application/use-project-knowledge-catalog";
import { useSinglePageDraft } from "./application/use-single-page-draft";
import { ExternalSourceList } from "./ExternalSourceList";
import { CategoryEditor } from "./presentation/CategoryEditor";
import { DiscoveryCardEditor } from "./presentation/DiscoveryCardEditor";
import { FaqAutoSyncSection } from "./presentation/FaqAutoSyncSection";
import { SinglePageEditor } from "./presentation/SinglePageEditor";
import { BusTimetableSection } from "./ProjectBusTimetable";
import type { KnowledgeCategoryKey } from "./project-knowledge-service";

type Props = {
  project: Project;
  editable?: boolean;
  canManageSources?: boolean;
};

/**
 * Knowledge workspace of one project: either the single LLM-fed page
 * (DIRECT_CONTEXT) or the reviewed per-category YAML catalog (RAG).
 * Composition only — the application hooks own data access, the presentation
 * modules own the markup.
 */
export const ProjectKnowledgePanel = ({
  project,
  editable = false,
  canManageSources = editable,
}: Props) => {
  if (project.knowledge_mode === "DIRECT_CONTEXT") {
    return <SinglePagePanel project={project} editable={canManageSources} />;
  }
  return (
    <RagCategoriesPanel
      project={project}
      editable={editable}
      canManageSources={canManageSources}
    />
  );
};

const SinglePagePanel = ({
  project,
  editable,
}: {
  project: Project;
  editable: boolean;
}) => {
  const draft = useSinglePageDraft(String(project.id), {
    isActive: project.is_active,
    canManageSources: editable,
  });

  return (
    <div className="space-y-4">
      <SinglePageEditor
        projectId={String(project.id)}
        draft={draft}
        editable={editable}
      />
      {editable && <DiscoveryCardEditor project={project} />}
    </div>
  );
};

const RagCategoriesPanel = ({
  project,
  editable,
  canManageSources,
}: {
  project: Project;
  editable: boolean;
  canManageSources: boolean;
}) => {
  const projectId = String(project.id);
  const [selected, setSelected] = useState<KnowledgeCategoryKey>("jobs");
  const [externalSourceSignal, setExternalSourceSignal] = useState(0);
  const categoryDetailRef = useRef<HTMLElement>(null);
  const catalog = useProjectKnowledgeCatalog(projectId);
  const draft = useCategoryDraft(projectId, selected, catalog);
  const faqAutoSyncOn = useFaqAutoSyncNotice(projectId, {
    enabled: canManageSources,
    refreshSignal: externalSourceSignal,
  });

  const { categories } = catalog;
  const selectedCategory = categories?.find((item) => item.key === selected);
  const selectedIsProcessing =
    catalog.processingKey === selected ||
    selectedCategory?.status === "STAGED" ||
    selectedCategory?.status === "PROCESSING";
  const activeCategoryCount =
    categories?.filter((item) => item.active_revision_id).length ?? 0;

  const selectCategory = (key: KnowledgeCategoryKey) => {
    if (
      draft.isEditing &&
      draft.hasUnsavedChanges &&
      !window.confirm("Bạn có thay đổi chưa lưu. Chuyển sang mục khác?")
    ) {
      return;
    }
    draft.cancelEditing();
    setSelected(key);

    if (!window.matchMedia("(max-width: 767px)").matches) return;

    window.requestAnimationFrame(() => {
      const detail = categoryDetailRef.current;
      if (!detail) return;
      const reducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      detail.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
      detail.focus({ preventScroll: true });
    });
  };

  return (
    <section
      className="project-knowledge-panel"
      aria-labelledby="project-knowledge-title"
    >
      <header className="project-knowledge-header">
        <h2 id="project-knowledge-title" className="project-knowledge-title">
          <Database className="size-5" aria-hidden="true" />
          Kiến thức theo danh mục
        </h2>
      </header>
      <div className="project-knowledge-content">
        <p className="project-knowledge-description">
          Việc làm có trong file = đang tuyển.
        </p>
        {categories && (
          <div className="project-knowledge-progress" aria-live="polite">
            <strong>
              {activeCategoryCount}/{categories.length} mục có dữ liệu
            </strong>
          </div>
        )}
        <div className="project-category-workspace">
          <nav
            className="project-category-navigation"
            aria-label="Danh mục kiến thức"
          >
            {categories && (
              <select
                className="project-category-mobile-select"
                value={selected}
                aria-label="Chọn danh mục kiến thức"
                onChange={(event) =>
                  selectCategory(event.target.value as KnowledgeCategoryKey)
                }
              >
                {categories.map((category) => (
                  <option key={category.key} value={category.key}>
                    {category.label_vi}
                    {category.active_revision_id
                      ? ` · v${category.active_revision_no ?? 1}`
                      : " · Chưa có dữ liệu"}
                  </option>
                ))}
              </select>
            )}
            {!categories ? (
              <div className="project-category-grid">
                {Array.from({ length: 12 }).map((_, index) => (
                  <Skeleton key={index} className="h-[72px]" />
                ))}
              </div>
            ) : (
              <div className="project-category-grid">
                {categories.map((category) => {
                  const isProcessing = catalog.processingKey === category.key;
                  const hasPendingRevision =
                    category.status === "STAGED" ||
                    category.status === "PROCESSING";
                  const hasError = category.status === "FAILED";
                  const isActive = Boolean(category.active_revision_id);
                  const isSelected = selected === category.key;
                  return (
                    <button
                      key={category.key}
                      type="button"
                      onClick={() => selectCategory(category.key)}
                      aria-pressed={isSelected}
                      aria-controls="project-category-detail"
                      className={cn(
                        "project-category-card",
                        isSelected && "is-selected",
                      )}
                    >
                      <div className="project-category-card-heading">
                        <span className="project-category-name">
                          {category.label_vi}
                        </span>
                        <span className="project-category-card-state">
                          {isProcessing || hasPendingRevision ? (
                            <span
                              className="tt-loading tt-loading-spinner tt-loading-sm text-primary"
                              aria-hidden="true"
                            />
                          ) : hasError ? (
                            <AlertCircle
                              className="size-4 text-destructive"
                              aria-hidden="true"
                            />
                          ) : isActive ? (
                            <Badge
                              variant="secondary"
                              className="h-6 px-1.5 text-badge font-semibold"
                              aria-label={`Đang dùng phiên bản ${category.active_revision_no ?? 1}`}
                            >
                              v{category.active_revision_no ?? 1}
                            </Badge>
                          ) : (
                            <span
                              className="project-category-empty-dot"
                              aria-hidden="true"
                            />
                          )}
                          <ChevronRight
                            className="project-category-chevron"
                            aria-hidden="true"
                          />
                        </span>
                      </div>
                      <div className="project-category-status">
                        {isProcessing || hasPendingRevision ? (
                          <span className="text-muted-foreground">
                            Đang xử lý
                          </span>
                        ) : hasError ? (
                          <span className="text-destructive">
                            Cập nhật lỗi — nội dung cũ vẫn đang dùng
                          </span>
                        ) : !isActive ? (
                          <span className="text-muted-foreground">
                            Chưa có dữ liệu
                          </span>
                        ) : null}
                      </div>
                      {category.updated_at && (
                        <p className="project-category-date">
                          Cập nhật {formatDate(category.updated_at)}
                        </p>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </nav>

          <CategoryEditor
            ref={categoryDetailRef}
            projectId={projectId}
            selectedKey={selected}
            category={selectedCategory}
            draft={draft}
            processing={selectedIsProcessing}
            editable={editable}
            canManageSources={canManageSources}
            onSourceCreated={() =>
              setExternalSourceSignal((value) => value + 1)
            }
          />
        </div>

        {selected === "faq" && (
          <FaqAutoSyncSection autoSyncOn={faqAutoSyncOn} />
        )}

        {canManageSources && (
          <section className="space-y-2">
            <h3 className="inline-flex items-center gap-2 text-body font-semibold">
              <Link2 className="size-4" aria-hidden="true" />
              Google Sheet
            </h3>
            <ExternalSourceList
              projectId={projectId}
              refreshSignal={externalSourceSignal}
              onChange={() => setExternalSourceSignal((value) => value + 1)}
            />
          </section>
        )}

        {selected === "transportation" && (
          <section className="project-transport-panel">
            <p className="project-transport-description">
              Lịch xe Agent tra cứu khi ứng viên hỏi tuyến, điểm đón, giờ đón.
            </p>
            <BusTimetableSection projectId={projectId} />
          </section>
        )}
      </div>
    </section>
  );
};

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
