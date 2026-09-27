import { useRef, useState } from "react";
import { ListBase, useNotify, usePermissions, useRefresh } from "ra-core";
import { useMasterDetailSelection } from "../hooks/useMasterDetailSelection";
import { usePipelineAutoRefresh } from "./usePipelineAutoRefresh";
import { BookOpen, FileText, RefreshCw, Search, Upload } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Confirm } from "@/components/admin/confirm";
import { ListPagination } from "@/components/admin/list-pagination";
import { KnowledgeUpload } from "./KnowledgeUpload";
import { KnowledgeVersionManager } from "./KnowledgeVersionManager";
import {
  flaggedCount,
  isPipelineActive,
  isPublished,
} from "./knowledgePipelineUtils";
import { InlineKnowledgeUploader } from "./InlineKnowledgeUploader";
import { KnowledgeDetailPanel } from "./KnowledgeDetailPanel";
import { KnowledgeSourceRow } from "./KnowledgeSourceRow";
import {
  ALL_PROJECTS,
  useKnowledgeSourceFilters,
} from "./useKnowledgeSourceFilters";
import { ProjectPicker } from "./ProjectPicker";
import { InboxIcons } from "../conversations/InboxIcons";
import { reindexAllKnowledge } from "./knowledge-service";
import { cn } from "@/lib/utils";
import "../conversations/inbox.css";
import type { KnowledgeSource } from "../types";

const RelearnIcon = ({ className }: { className?: string }) => (
  <RefreshCw aria-hidden="true" className={className} />
);

export const KnowledgeRelearnAction = () => {
  const { permissions } = usePermissions();
  const notify = useNotify();
  const refresh = useRefresh();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reindexPending, setReindexPending] = useState(false);

  if (permissions !== "admin") return null;

  const handleReindexAll = async () => {
    if (reindexPending) return;

    setReindexPending(true);
    try {
      const result = await reindexAllKnowledge();
      notify(`Đã xếp hàng học lại ${result.queued} nguồn kiến thức.`, {
        type: "success",
      });
      setConfirmOpen(false);
      refresh();
    } catch (error) {
      const detail =
        error instanceof Error && error.message ? ` ${error.message}` : "";
      notify(`Không thể xếp hàng học lại dữ liệu.${detail} Vui lòng thử lại.`, {
        type: "error",
      });
    } finally {
      setReindexPending(false);
    }
  };

  return (
    <>
      <Button
        type="button"
        variant="outline"
        disabled={reindexPending}
        onClick={() => setConfirmOpen(true)}
        className="knowledge-relearn-action tt-btn-touch h-11 w-full rounded-[9px] sm:w-fit"
      >
        <RelearnIcon
          className={cn(
            "size-4",
            reindexPending && "animate-spin motion-reduce:animate-none",
          )}
        />
        {reindexPending ? "Đang xếp hàng…" : "Học lại"}
      </Button>
      <Confirm
        isOpen={confirmOpen}
        loading={reindexPending}
        title="Học lại toàn bộ dữ liệu?"
        content="Hệ thống sẽ xử lý lại các nguồn đã xuất bản. Tác vụ chạy nền và có thể mất vài phút."
        cancel="Hủy"
        confirm={reindexPending ? "Đang xếp hàng…" : "Học lại"}
        ConfirmIcon={RelearnIcon}
        onClose={() => {
          if (!reindexPending) setConfirmOpen(false);
        }}
        onConfirm={() => void handleReindexAll()}
      />
    </>
  );
};

const KnowledgeSourceListContent = () => {
  const { permissions } = usePermissions();
  const [uploadOpen, setUploadOpen] = useState(false);

  const {
    isPending,
    sources,
    total,
    query,
    setQuery,
    projectFilter,
    selectProject,
  } = useKnowledgeSourceFilters();

  const { selectedId, setSelectedId } =
    useMasterDetailSelection<KnowledgeSource>({
      data: sources,
      autoSelectNewlyAppeared: true,
    });

  const selectedSource =
    sources.find((source) => String(source.id) === selectedId) ??
    sources[0] ??
    null;
  const uploadProjectId =
    projectFilter !== ALL_PROJECTS ? projectFilter : selectedSource?.project_id;

  // Auto-refresh only while something is actively moving through the pipeline;
  // stop when everything has settled, and never poll a hidden tab.
  usePipelineAutoRefresh(sources);

  const hasActive = sources.some(isPipelineActive);
  const hasSources = sources.length > 0;
  const readyCount = sources.filter(isPublished).length;
  const processingCount = sources.filter(isPipelineActive).length;
  const reviewCount = sources.reduce(
    (sum, source) => sum + flaggedCount(source),
    0,
  );
  const content = (
    <div className="kb-scope knowledge-workspace-content text-foreground">
      <div className="ops-page-shell knowledge-page-shell">
        <header className="ops-command-header knowledge-command-header">
          <div className="ops-command-title">
            <div className="ops-command-mark">
              <BookOpen className="size-5" />
            </div>
            <div className="min-w-0">
              <p className="ops-kicker">Trung tâm kiến thức</p>
              <h1>Quản lý kiến thức</h1>
              <p>Tìm, kiểm tra và cập nhật nguồn agent đang sử dụng.</p>
              {hasActive && (
                <span className="ops-live-pill">
                  <RefreshCw className="size-3.5 animate-spin motion-reduce:animate-none" />
                  Đang xử lý, tự làm mới mỗi 5 giây
                </span>
              )}
            </div>
          </div>
          {(hasSources || permissions === "admin") && (
            <div className="knowledge-command-actions">
              <div>
                <KnowledgeRelearnAction />
              </div>
              {hasSources && (
                <>
                  <div>
                    <KnowledgeVersionManager
                      projectId={
                        projectFilter !== ALL_PROJECTS
                          ? projectFilter
                          : undefined
                      }
                    />
                  </div>
                  <Button
                    type="button"
                    onClick={() => setUploadOpen(true)}
                    className="knowledge-primary-action tt-btn-touch h-11 w-full rounded-[9px] sm:w-fit"
                  >
                    <Upload className="size-4" />
                    Thêm tệp
                  </Button>
                </>
              )}
            </div>
          )}
        </header>

        <section className="ops-status-strip knowledge-status-strip">
          <div>
            <span className="ops-status-label">Nguồn</span>
            <strong>{total}</strong>
          </div>
          <div>
            <span className="ops-status-label">Sẵn sàng</span>
            <strong>{readyCount}</strong>
          </div>
          <div>
            <span className="ops-status-label">Xử lý</span>
            <strong>{processingCount}</strong>
          </div>
          <div>
            <span className="ops-status-label">Cần xem</span>
            <strong>{reviewCount}</strong>
          </div>
        </section>

        <KnowledgeUpload
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          initialProjectId={
            uploadProjectId ? String(uploadProjectId) : undefined
          }
        />

        <div className="knowledge-filter-bar">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Tìm tài liệu..."
              className="h-11 rounded-[9px] border-border bg-card pl-9 text-control"
            />
          </div>
          <div className="knowledge-filter-actions">
            <ProjectPicker
              value={projectFilter === ALL_PROJECTS ? "" : projectFilter}
              onChange={selectProject}
            />
            {projectFilter !== ALL_PROJECTS && (
              <Button
                type="button"
                variant="outline"
                onClick={() => selectProject(ALL_PROJECTS)}
                className="tt-btn-touch h-11 rounded-[9px]"
              >
                Tất cả
              </Button>
            )}
          </div>
        </div>

        {isPending ? (
          <SourceSelectorSkeleton />
        ) : sources.length === 0 ? (
          <div className="ops-panel knowledge-empty-panel">
            <InlineKnowledgeUploader />
          </div>
        ) : (
          <KnowledgeSourceWorkspace
            sources={sources}
            selectedSource={selectedSource}
            total={total}
            onSelect={setSelectedId}
          />
        )}
      </div>
    </div>
  );

  return (
    <div className="inbox-bg-container knowledge-workspace">
      <InboxIcons />
      <div className="app knowledge-app" id="app">
        <section className="panel center-panel knowledge-center-panel">
          {content}
        </section>
      </div>
    </div>
  );
};

export const KnowledgeSourceWorkspace = ({
  sources,
  selectedSource,
  total,
  onSelect,
}: {
  sources: ReturnType<typeof useKnowledgeSourceFilters>["sources"];
  selectedSource:
    | ReturnType<typeof useKnowledgeSourceFilters>["sources"][number]
    | null;
  total: number;
  onSelect: (id: string) => void;
}) => {
  const detailRef = useRef<HTMLElement>(null);
  const navigationRef = useRef<HTMLElement>(null);

  const selectSource = (id: string) => {
    onSelect(id);

    if (!window.matchMedia("(max-width: 760px)").matches) return;

    window.requestAnimationFrame(() => {
      const detail = detailRef.current;
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

  const returnToSourceList = () => {
    const navigation = navigationRef.current;
    if (!navigation) return;
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    navigation.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start",
    });
  };

  return (
    <section
      className="knowledge-source-workspace"
      aria-label="Duyệt nguồn kiến thức"
    >
      <aside
        ref={navigationRef}
        className="knowledge-source-navigation"
        aria-labelledby="knowledge-source-list-title"
      >
        <header className="knowledge-source-navigation-header">
          <div className="ops-panel-title">
            <p className="ops-panel-eyebrow">Tài liệu</p>
            <h2 id="knowledge-source-list-title">Nguồn kiến thức</h2>
          </div>
          <span className="knowledge-source-count">{total}</span>
        </header>

        <div className="knowledge-source-list" role="list">
          {sources.map((source) => (
            <KnowledgeSourceRow
              key={source.id}
              source={source}
              selected={String(source.id) === String(selectedSource?.id)}
              onSelect={() => selectSource(String(source.id))}
            />
          ))}
        </div>

        <ListPagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          className="knowledge-source-pagination"
        />
      </aside>

      <section
        ref={detailRef}
        id="knowledge-source-detail"
        className="knowledge-source-detail"
        tabIndex={-1}
        aria-labelledby={
          selectedSource ? "knowledge-source-detail-title" : undefined
        }
      >
        {selectedSource ? (
          <KnowledgeDetailPanel
            source={selectedSource}
            headingId="knowledge-source-detail-title"
            onBack={returnToSourceList}
          />
        ) : (
          <EmptyState
            icon={<FileText className="size-6" />}
            title="Chọn một nguồn kiến thức"
            description="Nội dung và thao tác sẽ hiện tại đây."
            className="min-h-[420px]"
          />
        )}
      </section>
    </section>
  );
};

const SourceSelectorSkeleton = () => (
  <section className="knowledge-source-workspace knowledge-source-workspace--loading">
    <div className="knowledge-source-navigation" aria-hidden="true">
      <div className="knowledge-source-navigation-header">
        <div className="space-y-2">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-5 w-36" />
        </div>
        <Skeleton className="size-8 rounded-full" />
      </div>
      <div className="knowledge-source-list">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="flex min-h-[88px] items-start gap-3 border-b border-border px-4 py-3"
          >
            <Skeleton className="mt-1 size-4 shrink-0" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-3 w-3/5" />
            </div>
          </div>
        ))}
      </div>
    </div>
    <div
      className="knowledge-source-detail flex min-h-[420px] flex-col gap-4"
      aria-hidden="true"
    >
      <div className="space-y-2">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-3 w-1/2" />
      </div>
      <Skeleton className="h-11 w-64 max-w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  </section>
);

export const KnowledgeSourceList = () => (
  <ListBase perPage={10} sort={{ field: "updated_at", order: "DESC" }}>
    <KnowledgeSourceListContent />
  </ListBase>
);
