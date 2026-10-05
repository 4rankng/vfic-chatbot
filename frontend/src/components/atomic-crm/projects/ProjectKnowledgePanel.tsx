import { useRef, useState, type ReactNode } from "react";
import { AlertCircle, Database, Upload } from "lucide-react";
import { useNotify, useRefresh } from "ra-core";

import { ChevronDown, FileDownload02, Loading01 } from "@untitledui/icons";

import { Badge } from "@/components/base/badges/badges";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import { Button } from "@/components/base/buttons/button";
import { Select as UntitledSelect } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";
import { cn } from "@/lib/utils";
import type { Project } from "../types";
import {
  PROJECT_KNOWLEDGE_CATEGORIES,
  PROJECT_KNOWLEDGE_CATEGORY_LABELS,
  type ProjectKnowledgeCategory,
} from "./domain/project-knowledge-policy";
import { useCategoryDraft } from "./presentation/use-category-draft";
import { useProjectKnowledgeCatalog } from "./presentation/use-project-knowledge-catalog";
import { useProjectIngest } from "./presentation/use-project-ingest";
import { useBriefFileIngest } from "./presentation/use-brief-file-ingest";
import type { BriefFileIngest } from "./presentation/use-brief-file-ingest";
import { IngestProgressBoard } from "./presentation/IngestProgressBoard";
import { useSinglePageDraft } from "./presentation/use-single-page-draft";
import { WorkspaceCommandBar } from "./presentation/WorkspaceCommandBar";
import {
  ProjectKnowledgeExport,
  useKnowledgeDownload,
} from "./ProjectKnowledgeExport";
import { CategoryEditor } from "./presentation/CategoryEditor";
import { DiscoveryCardEditor } from "./presentation/DiscoveryCardEditor";
import { SinglePageEditor } from "./presentation/SinglePageEditor";
import { BusTimetableSection } from "./ProjectBusTimetable";
import {
  clearProjectKnowledgeCategory,
  cutoverProjectKnowledgeCategories,
  getProjectKnowledgeCategories,
  getProjectKnowledgeFullTemplate,
  PROJECT_TEXT_FILE_ACCEPT,
  assertProjectTextFile,
  type KnowledgeCategoryKey,
} from "./project-knowledge-service";

type Props = {
  project: Project;
  editable?: boolean;
  canManageSources?: boolean;
  /** Row-leading controls (edit/toggle/delete) shown beside the KB export. */
  toolbar?: ReactNode;
};

/**
 * Knowledge workspace of one project: either the single LLM-fed page
 * (DIRECT_CONTEXT) or the reviewed per-category markdown catalog (RAG).
 * Composition only — the application hooks own data access, the presentation
 * modules own the markup.
 */
const KnowledgeExportAction = ({ projectId }: { projectId: string }) => (
  <ProjectKnowledgeExport key={projectId} projectId={projectId} />
);

export const ProjectKnowledgePanel = ({
  project,
  editable = false,
  canManageSources = editable,
  toolbar,
}: Props) => {
  const showBar = Boolean(toolbar) || canManageSources;
  const leading = showBar ? toolbar : undefined;
  return (
    <div className="space-y-3">
      {project.knowledge_mode === "DIRECT_CONTEXT" ? (
        <SinglePagePanel
          project={project}
          editable={canManageSources}
          leading={leading}
          showExport={canManageSources}
        />
      ) : project.knowledge_mode === "RAG" ? (
        <RagCategoriesPanel
          project={project}
          editable={editable}
          canManageSources={canManageSources}
          leading={leading}
        />
      ) : (
        <>
          {showBar && (
            <WorkspaceCommandBar
              leading={leading}
              trailing={
                canManageSources ? (
                  <KnowledgeExportAction projectId={String(project.id)} />
                ) : undefined
              }
            />
          )}
          <section
            className="project-legacy-knowledge"
            aria-label="Kiến thức cũ"
          >
            <Database
              className="size-5 text-muted-foreground"
              aria-hidden="true"
            />
            <div>
              <h2 className="text-section-title font-semibold">
                Kiến thức chưa được chuyển đổi
              </h2>
              <p className="text-helper text-muted-foreground">
                Dự án chưa có KB riêng để quản lý theo danh mục. Tài liệu hiện
                có được giữ lại.
              </p>
              {canManageSources && (
                <p className="text-helper text-muted-foreground">
                  Hoàn tất chuyển đổi kiến thức của dự án trước khi chỉnh sửa
                  danh mục.
                </p>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
};

const SinglePagePanel = ({
  project,
  editable,
  leading,
  showExport,
}: {
  project: Project;
  editable: boolean;
  leading?: ReactNode;
  showExport?: boolean;
}) => {
  const draft = useSinglePageDraft(String(project.id), {
    isActive: project.is_active,
  });

  return (
    <div className="space-y-4">
      {(leading || showExport) && (
        <WorkspaceCommandBar
          leading={leading}
          trailing={
            showExport ? (
              <KnowledgeExportAction projectId={String(project.id)} />
            ) : undefined
          }
        />
      )}
      <SinglePageEditor draft={draft} editable={editable} />
      {/* The one-brief migration to the 12-category catalog is an admin move:
          the clear and cutover calls it finishes with are admin endpoints. */}
      {editable && <MigrationSection projectId={String(project.id)} />}
      {editable && <DiscoveryCardEditor project={project} />}
    </div>
  );
};

/**
 * Text-brief ingestion for an EXISTING RAG project: the recruiter picks one
 * text source; the backend reviews its full content and owns category writes.
 * A browser preview never determines the category set or completion.
 */
const BriefIngestSection = ({
  projectId,
  disabled,
  buttonLabel = "Nhập từ tệp văn bản",
  onIngested,
  onCutover,
}: {
  projectId: string;
  disabled: boolean;
  /** The upload button's label; the migration affordance renames it. */
  buttonLabel?: string;
  /**
   * Refreshes the catalog after review. This does not authorize publishing a
   * shadow source's highlights or hand knowledge authority to its categories.
   */
  onIngested?: (
    categories: readonly ProjectKnowledgeCategory[],
  ) => Promise<void>;
  /** Resolves only after the explicit category-authority cutover succeeds. */
  onCutover?: (
    categories: readonly ProjectKnowledgeCategory[],
  ) => Promise<void>;
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const { state, ingest } = useProjectIngest();
  /** Vietnamese labels of the categories this brief cannot seed. */
  const [needsHuman, setNeedsHuman] = useState<string[] | null>(null);
  const [error, setError] = useState("");

  const read = async (file?: File) => {
    if (!file) return;
    setError("");
    setNeedsHuman(null);
    try {
      assertProjectTextFile(file);
      const result = await ingest(projectId, [], file);
      if (!result.ok) return;
      setNeedsHuman(
        PROJECT_KNOWLEDGE_CATEGORIES.filter(
          (key) => !result.activated.includes(key),
        ).map((key) => PROJECT_KNOWLEDGE_CATEGORY_LABELS[key]),
      );
      // Review can finish as a shadow batch while the single-page source is
      // still live. Complete the explicit migration before publishing claims.
      if (result.requiresCutover && !onCutover) {
        // Another admin may have rolled back while this RAG panel was open.
        // A catalog reload cannot make the prepared source authoritative.
        await onIngested?.(result.activated);
        return;
      }
      // The migration's explicit intent also applies to older receipts that
      // omit requires_cutover. Never infer successful cutover from a reload.
      await onCutover?.(result.activated);
      await onIngested?.(result.activated);
    } catch (readError) {
      setError((readError as Error).message);
    } finally {
      // Allow re-picking the same file after an edit.
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const ingesting = state.phase === "running";
  return (
    <section
      className="project-brief-ingest"
      aria-label="Nhập kiến thức từ phiếu thông tin"
    >
      <div className="project-brief-ingest-heading">
        <div>
          <p className="text-body font-semibold">Cập nhật kiến thức từ tệp</p>
          <p className="text-helper text-muted-foreground">
            Một tệp văn bản (.txt, .md, .csv…) hoặc tệp Word (.docx), tối đa 20
            MB. Không cần theo mẫu.
          </p>
        </div>
        {/*
          The file affordance is a Untitled UI button plus a visually hidden
          input, not a `<label>` inside a button: the library's `Button` is a
          React Aria button with no `asChild`, and `click()` on the input keeps
          the control's role, name and busy state on the button itself.
        */}
        <Button
          type="button"
          color="secondary"
          size="sm"
          className="uu-scope"
          iconLeading={Upload}
          isLoading={ingesting}
          showTextWhileLoading
          isDisabled={disabled || ingesting}
          onClick={() => inputRef.current?.click()}
        >
          {buttonLabel}
        </Button>
        <input
          ref={inputRef}
          type="file"
          hidden
          accept={PROJECT_TEXT_FILE_ACCEPT}
          className="sr-only"
          aria-label="Chọn tệp phiếu thông tin dự án"
          disabled={disabled || ingesting}
          onChange={(event) => void read(event.target.files?.[0])}
        />
      </div>
      {state.phase === "running" ? (
        <>
          <p role="status" className="text-helper text-foreground">
            {state.current
              ? `Đang nạp «${PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.current]}» (${state.items.findIndex((item) => item.key === state.current) + 1}/${state.total})…`
              : "Đang phân loại nội dung tệp…"}
          </p>
          <IngestProgressBoard items={state.items} slow={state.slow} />
        </>
      ) : null}
      {state.phase === "done" ? (
        <p role="status" className="text-helper text-foreground">
          {state.requiresCutover
            ? `Đã chuẩn bị và kiểm tra ${state.activated.length} phần kiến thức từ phiếu. Cần hoàn tất bước chuyển sang 12 danh mục trước khi Chatbot sử dụng dữ liệu mới. Nguồn kiến thức hiện tại vẫn được dùng.`
            : `Đã nạp xong ${state.activated.length} phần kiến thức từ phiếu.`}
          {needsHuman && needsHuman.length > 0
            ? ` Cần nhập tay: ${needsHuman.join(", ")}.`
            : ""}
        </p>
      ) : null}
      {state.phase === "failed" ? (
        <p role="alert" className="text-helper text-destructive">
          {state.failed
            ? `Chưa xác nhận hoàn tất «${PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.failed]}»`
            : "Chưa nạp được tệp"}
          {state.message ? `: ${state.message}` : "."} Kiểm tra trạng thái danh
          mục trước khi nạp lại. Các phần đã xác nhận vẫn được giữ.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-helper text-destructive">
          {error}
        </p>
      ) : null}
    </section>
  );
};

/**
 * The single-page → 12-category migration: one brief upload runs the same
 * ingest chain the RAG panel uses, then — only after every carried category is
 * active — the categories the brief does not carry are explicitly cleared and
 * the cutover hands the project's knowledge authority to the catalog. The
 * cutover moves the knowledge base out of DIRECT_CONTEXT, so the panel
 * re-renders as the category catalog once the project record is re-read; a
 * failure anywhere before it leaves the single page untouched. The backend's
 * rollback endpoint restores the captured single-page state afterwards.
 */
const MigrationSection = ({ projectId }: { projectId: string }) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const [migrating, setMigrating] = useState(false);

  const migrate = async (confirmed: readonly ProjectKnowledgeCategory[]) => {
    setMigrating(true);
    try {
      // A partial brief must preserve existing revisions, including categories
      // that still need review. Only a genuinely empty, unwritten category
      // needs an explicit empty state before cutover.
      const catalog = await getProjectKnowledgeCategories(projectId);
      const writtenKeys = new Set(confirmed);
      for (const key of PROJECT_KNOWLEDGE_CATEGORIES) {
        const category = catalog.data.find((item) => item.key === key);
        if (
          writtenKeys.has(key) ||
          category?.active_revision_id ||
          category?.status === "CLEARED"
        ) {
          continue;
        }
        if (
          category?.latest_revision_id ||
          category?.latest_revision_no ||
          category?.status === "STAGED" ||
          category?.status === "PROCESSING"
        ) {
          throw new Error(
            "Một danh mục đã có phiên bản chưa được kích hoạt. Hãy kiểm tra trước khi chuyển đổi.",
          );
        }
        await clearProjectKnowledgeCategory(projectId, key, 0);
      }
      await cutoverProjectKnowledgeCategories(projectId);
      notify("Dự án đã chuyển sang kiến thức 12 danh mục.", {
        type: "success",
      });
      // The cutover changed what the project record reads as; re-read it so
      // this panel comes back as the category catalog.
      refresh();
    } catch (error) {
      // The chain itself already landed; name the cutover half so the
      // recruiter knows the single page is still the live knowledge.
      throw new Error(
        `Đã nạp kiến thức nhưng chưa chuyển được sang 12 danh mục: ${
          (error as Error).message
        }`,
      );
    } finally {
      setMigrating(false);
    }
  };

  return (
    <section
      className="project-migration-section grid gap-2"
      aria-label="Chuyển sang kiến thức 12 danh mục"
    >
      <div>
        <h3 className="inline-flex items-center gap-2 text-body font-semibold">
          <Database className="size-4" aria-hidden="true" />
          Chuyển sang kiến thức 12 danh mục
        </h3>
        <p className="text-helper text-muted-foreground">
          Nạp tệp để phân loại kiến thức. Danh mục đã có dữ liệu được giữ lại
          nếu tệp không nêu. Kiến thức hiện tại vẫn được dùng đến khi chuyển
          xong. Giữ trang mở; nếu rời trang, chọn lại cùng tệp để tiếp tục.
        </p>
      </div>
      <BriefIngestSection
        projectId={projectId}
        disabled={migrating}
        buttonLabel="Nhập tệp và chuyển đổi"
        onCutover={migrate}
      />
    </section>
  );
};

const RagCategoriesPanel = ({
  project,
  editable,
  canManageSources,
  leading,
}: {
  project: Project;
  editable: boolean;
  canManageSources: boolean;
  leading?: ReactNode;
}) => {
  const projectId = String(project.id);
  const [selected, setSelected] = useState<KnowledgeCategoryKey>("jobs");
  const categoryDetailRef = useRef<HTMLElement>(null);
  const catalog = useProjectKnowledgeCatalog(projectId);
  const draft = useCategoryDraft(projectId, selected, catalog);
  const ingest = useBriefFileIngest(projectId, {
    disabled: !canManageSources || !editable,
    onIngested: async () => {
      await catalog.reload();
    },
  });
  const templateDownload = useKnowledgeDownload({
    projectId,
    getFile: getProjectKnowledgeFullTemplate,
    emptyMessage: "Mẫu KB chưa có nội dung. Vui lòng thử lại.",
    failureMessage: "Chưa tải được mẫu KB. Vui lòng thử lại.",
  });

  const { categories } = catalog;
  const selectedCategory = categories?.find((item) => item.key === selected);
  const selectedIsProcessing =
    catalog.processingKey === selected ||
    selectedCategory?.status === "STAGED" ||
    selectedCategory?.status === "PROCESSING";
  const activeCategoryCount =
    categories?.filter((item) => item.active_revision_id).length ?? 0;
  /** The phone-only category picker offers exactly what the card grid shows:
   *  the label plus the active revision, or a "no data" note. */
  const categoryItems: SelectItemType[] = (categories ?? []).map(
    (category) => ({
      id: category.key,
      label: `${category.label_vi}${
        category.active_revision_id
          ? ` · v${category.active_revision_no ?? 1}`
          : " · Chưa có dữ liệu"
      }`,
    }),
  );

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

  const importMenu =
    canManageSources &&
    editable &&
    project.category_authority_started !== false ? (
      <KnowledgeImportMenu
        onPickFile={() => ingest.inputRef.current?.click()}
        onTemplate={() => templateDownload.download()}
      />
    ) : null;

  return (
    <section
      className="project-knowledge-panel"
      aria-labelledby="project-knowledge-title"
    >
      <h2 id="project-knowledge-title" className="sr-only">
        Kiến thức theo danh mục
      </h2>
      {(leading || canManageSources) && (
        <WorkspaceCommandBar
          leading={leading}
          trailing={
            <>
              {importMenu}
              {canManageSources && (
                <KnowledgeExportAction projectId={projectId} />
              )}
            </>
          }
        />
      )}
      <div className="project-knowledge-content">
        {canManageSources &&
          editable &&
          (project.category_authority_started === false ? (
            <MigrationSection projectId={projectId} />
          ) : (
            <RagIngestStrip ingest={ingest} />
          ))}
        <div className="project-category-workspace">
          <nav
            className="project-category-navigation"
            aria-label="Danh mục kiến thức"
          >
            <div className="project-category-rail-caption">
              <span>Danh mục kiến thức</span>
              {categories && (
                <span
                  className="project-category-rail-count"
                  aria-live="polite"
                >
                  {activeCategoryCount}/{categories.length} có dữ liệu
                </span>
              )}
            </div>
            {categories && (
              <UntitledSelect
                id="project-category-mobile-select"
                className="project-category-mobile-select uu-scope"
                aria-label="Chọn danh mục kiến thức"
                size="sm"
                placeholder=""
                items={categoryItems}
                selectedKey={selected}
                onSelectionChange={(key) => {
                  if (key !== null) selectCategory(key as KnowledgeCategoryKey);
                }}
                validationBehavior="aria"
              >
                {(item: SelectItemType) => (
                  <UntitledSelect.Item id={item.id} label={item.label} />
                )}
              </UntitledSelect>
            )}
            {!categories ? (
              <div
                className="project-category-grid"
                role="status"
                aria-label="Đang tải danh sách"
              >
                {Array.from({ length: 12 }).map((_, index) => (
                  <span
                    key={index}
                    className="block h-10 animate-pulse rounded-md bg-[var(--surface-hover)]"
                  />
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
                      aria-label={
                        hasError
                          ? `${category.label_vi} — cập nhật lỗi, nội dung cũ vẫn đang dùng`
                          : undefined
                      }
                      title={
                        hasError
                          ? "Cập nhật lỗi — nội dung cũ vẫn đang dùng"
                          : undefined
                      }
                      className={cn(
                        "project-category-card",
                        isSelected && "is-selected",
                      )}
                    >
                      <span className="project-category-name">
                        {category.label_vi}
                      </span>
                      <span className="project-category-card-state">
                        {isProcessing || hasPendingRevision ? (
                          <Loading01
                            className="size-4 shrink-0 animate-spin text-primary"
                            aria-hidden="true"
                          />
                        ) : hasError ? (
                          <AlertCircle
                            className="size-4 text-destructive"
                            aria-label="Cập nhật lỗi — nội dung cũ vẫn đang dùng"
                          />
                        ) : isActive ? (
                          <Badge
                            className="uu-scope"
                            type="pill-color"
                            size="sm"
                            color="gray"
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
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </nav>

          <CategoryEditor
            ref={categoryDetailRef}
            selectedKey={selected}
            category={selectedCategory}
            draft={draft}
            processing={selectedIsProcessing}
            editable={editable}
          />
        </div>

        {selected === "transportation" && (
          <section className="project-transport-panel">
            <p className="project-transport-description">
              Lịch xe chatbot tra cứu khi ứng viên hỏi tuyến, điểm đón, giờ đón.
            </p>
            <BusTimetableSection projectId={projectId} />
          </section>
        )}
      </div>
    </section>
  );
};

/** The command bar's import menu: the file chain and the full-template
 *  download. The hidden input itself lives beside the ingest strip, outside
 *  any popover, so a closed menu never unmounts it. */
const KnowledgeImportMenu = ({
  onPickFile,
  onTemplate,
}: {
  onPickFile: () => void;
  onTemplate: () => void;
}) => (
  <Dropdown.Root>
    <Button type="button" color="primary" size="sm" iconTrailing={ChevronDown}>
      Nhập
    </Button>
    <Dropdown.Popover>
      <Dropdown.Menu
        onAction={(key) => (key === "file" ? onPickFile() : onTemplate())}
      >
        <Dropdown.Item id="file" label="Từ tệp văn bản…" icon={Upload} />
        <Dropdown.Item id="template" label="Tải mẫu KB" icon={FileDownload02} />
      </Dropdown.Menu>
    </Dropdown.Popover>
  </Dropdown.Root>
);

/** Idle-quiet ingest strip of the RAG workspace: the permanent hidden file
 *  input plus the progress and result messages; there is no heading or button
 *  because the command bar's import menu owns the entry point. */
const RagIngestStrip = ({ ingest }: { ingest: BriefFileIngest }) => {
  const { state } = ingest;
  return (
    <section
      className="project-rag-ingest-strip"
      aria-label="Nhập kiến thức từ tệp"
    >
      <input
        ref={ingest.inputRef}
        type="file"
        hidden
        accept={PROJECT_TEXT_FILE_ACCEPT}
        className="sr-only"
        aria-label="Chọn tệp phiếu thông tin dự án"
        disabled={ingest.ingesting}
        onChange={(event) => void ingest.read(event.target.files?.[0])}
      />
      {state.phase === "running" ? (
        <>
          <p role="status" className="text-helper text-foreground">
            {state.current
              ? `Đang nạp «${PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.current]}» (${state.items.findIndex((item) => item.key === state.current) + 1}/${state.total})…`
              : "Đang phân loại nội dung tệp…"}
          </p>
          <IngestProgressBoard items={state.items} slow={state.slow} />
        </>
      ) : null}
      {state.phase === "done" ? (
        <p role="status" className="text-helper text-foreground">
          {state.requiresCutover
            ? `Đã chuẩn bị và kiểm tra ${state.activated.length} phần kiến thức từ phiếu. Cần hoàn tất bước chuyển sang 12 danh mục trước khi Chatbot sử dụng dữ liệu mới. Nguồn kiến thức hiện tại vẫn được dùng.`
            : `Đã nạp xong ${state.activated.length} phần kiến thức từ phiếu.`}
          {ingest.needsHuman && ingest.needsHuman.length > 0
            ? ` Cần nhập tay: ${ingest.needsHuman.join(", ")}.`
            : ""}
        </p>
      ) : null}
      {state.phase === "failed" ? (
        <p role="alert" className="text-helper text-destructive">
          {state.failed
            ? `Chưa xác nhận hoàn tất «${PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.failed]}»`
            : "Chưa nạp được tệp"}
          {state.message ? `: ${state.message}` : "."} Kiểm tra trạng thái danh
          mục trước khi nạp lại. Các phần đã xác nhận vẫn được giữ.
        </p>
      ) : null}
      {ingest.error ? (
        <p role="alert" className="text-helper text-destructive">
          {ingest.error}
        </p>
      ) : null}
    </section>
  );
};
