import { useRef, useState } from "react";
import {
  AlertCircle,
  ChevronRight,
  Database,
  Link2,
  Upload,
} from "lucide-react";
import { useNotify, useRefresh } from "ra-core";

import { Loading01 } from "@untitledui/icons";

import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Select as UntitledSelect } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";
import { cn } from "@/lib/utils";
import type { Project } from "../types";
import { parseProjectBrief } from "./domain/project-brief-ingest";
import { PROJECT_KNOWLEDGE_CATEGORY_LABELS } from "./domain/project-knowledge-policy";
import {
  planBriefKnowledge,
  type BriefKnowledgePlan,
} from "./domain/project-knowledge-markdown";
import { useCategoryDraft } from "./presentation/use-category-draft";
import { useFaqAutoSyncNotice } from "./presentation/use-faq-auto-sync-notice";
import { useProjectKnowledgeCatalog } from "./presentation/use-project-knowledge-catalog";
import { useProjectIngest } from "./presentation/use-project-ingest";
import { IngestProgressBoard } from "./presentation/IngestProgressBoard";
import { useSinglePageDraft } from "./presentation/use-single-page-draft";
import { ExternalSourceList } from "./ExternalSourceList";
import { CategoryEditor } from "./presentation/CategoryEditor";
import { DiscoveryCardEditor } from "./presentation/DiscoveryCardEditor";
import { FaqAutoSyncSection } from "./presentation/FaqAutoSyncSection";
import { SinglePageEditor } from "./presentation/SinglePageEditor";
import { BusTimetableSection } from "./ProjectBusTimetable";
import {
  clearProjectKnowledgeCategory,
  cutoverProjectKnowledgeCategories,
  updateProjectDiscoveryCard,
  type KnowledgeCategoryKey,
} from "./project-knowledge-service";

type Props = {
  project: Project;
  editable?: boolean;
  canManageSources?: boolean;
};

/**
 * Knowledge workspace of one project: either the single LLM-fed page
 * (DIRECT_CONTEXT) or the reviewed per-category markdown catalog (RAG).
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
      {/* The one-brief migration to the 12-category catalog is an admin move:
          the clear and cutover calls it finishes with are admin endpoints. */}
      {editable && <MigrationSection projectId={String(project.id)} />}
      {editable && <DiscoveryCardEditor project={project} />}
    </div>
  );
};

/** A brief is a document a person typed; anything wildly past that is a
 *  mis-drop, and reading it would freeze the tab. */
const MAX_BRIEF_BYTES = 2 * 1024 * 1024;

/** Clearly non-text shapes — binary documents, images, media, archives — by
 *  extension or by MIME type. A .md/.txt file, one with no extension, or one
 *  with an unknown extension is text the parser gets to judge. Mirrors the
 *  guard in ProjectBriefImport. */
const BINARY_NAME =
  /\.(pdf|docx?|xlsx?|pptx?|odt|ods|odp|png|jpe?g|gif|bmp|tiff?|ico|webp|mp3|mp4|mov|avi|wav|ogg|flac|zip|rar|7z|tar|gz|exe|dmg|apk|bin)$/i;
const BINARY_TYPE =
  /^(image|audio|video|font)\/|^application\/(pdf|zip|gzip|x-tar|x-rar-compression|x-7z-compressed|msword|vnd\.ms-|vnd\.openxmlformats-|vnd\.oasis\.)/i;

/**
 * Text-brief ingestion for an EXISTING RAG project: the recruiter picks one
 * text brief (markdown is the recommended format), the domain parser proposes,
 * and the create flow's own ingest chain writes every genuinely-carried
 * category jobs-first, awaiting real activation per category. A section the
 * sheet does not carry — or only carries as a template instruction — is named
 * "cần nhập tay", never invented.
 *
 * Every pick is a full re-ingest: the file is parsed fresh and the complete
 * write set runs again — an already-active category is superseded, never a
 * reason to skip — with the file itself uploaded as a project document. No
 * confirmation gates the run: a superseded revision stays archived and
 * auditable, so a re-ingest is an update, not a destructive act.
 */
const BriefIngestSection = ({
  projectId,
  disabled,
  buttonLabel = "Nhập từ tệp văn bản (.md khuyến nghị)",
  onIngested,
}: {
  projectId: string;
  disabled: boolean;
  /** The upload button's label; the migration affordance renames it. */
  buttonLabel?: string;
  /**
   * Runs after the chain lands and the brief's highlights are patched onto the
   * discovery card. A throw surfaces through this section's error state — the
   * single page and the written categories are untouched either way.
   */
  onIngested?: (plan: BriefKnowledgePlan) => Promise<void>;
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
    // Text files only, by product ruling: every text shape is parsed —
    // markdown is just the recommended format — while a clearly binary pick
    // (pdf, image, office) is rejected before any read.
    if (BINARY_NAME.test(file.name) || BINARY_TYPE.test(file.type)) {
      setError("Chỉ chấp nhận tệp văn bản.");
      return;
    }
    if (file.size > MAX_BRIEF_BYTES) {
      setError("Tệp quá lớn. Hãy tải lên phiếu thông tin dưới 2 MB.");
      return;
    }
    try {
      const brief = parseProjectBrief(await file.text());
      const plan = planBriefKnowledge(brief);
      if (plan.writes.length === 0) {
        setError(
          "Không đọc được nội dung dự án từ tệp này. Hãy kiểm tra lại tệp văn bản.",
        );
        return;
      }
      setNeedsHuman(
        plan.needsHuman.map((key) => PROJECT_KNOWLEDGE_CATEGORY_LABELS[key]),
      );
      // No prompt before the writes: each one supersedes its category's
      // active revision while the old revision stays archived, so asking
      // first would only gate an update. The brief file rides along as a
      // project document (best-effort — its failure never blocks the writes).
      // The chain reports failure through its state, not a throw — so the
      // continuation checks the landed flag instead of relying on the catch.
      const landed = await ingest(projectId, plan.writes, file);
      // Every re-ingest re-lands the brief's highlight facts on the discovery
      // card: the activation projection preserves `highlights` (it only seeds
      // them), so the facts survive every later projection run. A brief with
      // no highlights sends nothing — the card keeps its derived empty list.
      if (brief.highlights.length > 0) {
        await updateProjectDiscoveryCard(projectId, {
          discovery_card: { highlights: brief.highlights },
        });
      }
      if (landed) await onIngested?.(plan);
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
      className="project-brief-ingest grid gap-2"
      aria-label="Nhập kiến thức từ phiếu thông tin"
    >
      <div className="flex flex-wrap items-center gap-3">
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
          accept=".md,.txt,.markdown,text/plain,text/markdown"
          className="sr-only"
          aria-label="Chọn tệp phiếu thông tin dự án"
          disabled={disabled || ingesting}
          onChange={(event) => void read(event.target.files?.[0])}
        />
      </div>
      {state.phase === "running" ? (
        <>
          <p role="status" className="text-helper text-foreground">
            Đang nạp «{PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.current]}» (
            {state.activated.length + 1}/{state.total})…
          </p>
          <IngestProgressBoard items={state.items} slow={state.slow} />
        </>
      ) : null}
      {state.phase === "done" ? (
        <p role="status" className="text-helper text-foreground">
          Đã nạp xong {state.activated.length} phần kiến thức từ phiếu.
          {needsHuman && needsHuman.length > 0
            ? ` Cần nhập tay: ${needsHuman.join(", ")}.`
            : ""}
        </p>
      ) : null}
      {state.phase === "failed" ? (
        <p role="alert" className="text-helper text-destructive">
          Nạp «{PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.failed]}» không thành
          công{state.message ? `: ${state.message}` : "."} Dữ liệu đang dùng của
          mục này không thay đổi.
        </p>
      ) : null}
      {(state.phase === "done" || state.phase === "failed") &&
      state.uploadError ? (
        <p role="alert" className="text-helper text-destructive">
          Tệp phiếu chưa được lưu vào tài liệu dự án: {state.uploadError}. Nội
          dung các mục đã nạp vẫn được giữ.
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

  const migrate = async (plan: BriefKnowledgePlan) => {
    setMigrating(true);
    try {
      // Cutover rejects a project whose categories are neither active nor
      // explicitly cleared, so every category the brief does not carry is
      // cleared first — an explicit empty state, not a gap.
      for (const key of plan.needsHuman) {
        await clearProjectKnowledgeCategory(projectId, key);
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
          Dự án này đang dùng kiến thức một trang. Hãy tải lên phiếu thông tin
          dạng văn bản: hệ thống nạp các danh mục theo tệp, mục nào phiếu không
          nêu sẽ được đánh dấu trống, rồi dự án chuyển hẳn sang quản lý theo 12
          danh mục. Trang một trang hiện tại được giữ lại và có thể khôi phục.
        </p>
      </div>
      <BriefIngestSection
        projectId={projectId}
        disabled={migrating}
        buttonLabel="Chuyển sang 12 danh mục — nhập từ tệp .md"
        onIngested={migrate}
      />
    </section>
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
              {activeCategoryCount}/{categories.length} danh mục có dữ liệu
            </strong>
          </div>
        )}
        {canManageSources && editable && (
          <BriefIngestSection projectId={projectId} disabled={false} />
        )}
        <div className="project-category-workspace">
          <nav
            className="project-category-navigation"
            aria-label="Danh mục kiến thức"
          >
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
                    className="block h-[72px] animate-pulse rounded-md bg-[var(--surface-hover)]"
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
                            <Loading01
                              className="size-4 shrink-0 animate-spin text-primary"
                              aria-hidden="true"
                            />
                          ) : hasError ? (
                            <AlertCircle
                              className="size-4 text-destructive"
                              aria-hidden="true"
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
