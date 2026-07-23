import { useEffect, useState } from "react";
import { ListBase, useNotify, usePermissions, useRefresh } from "ra-core";
import { useMasterDetailSelection } from "../hooks/useMasterDetailSelection";
import { BookOpen, FileText, RefreshCw, Search, Upload } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Confirm } from "@/components/admin/confirm";
import { ListPagination } from "@/components/admin/list-pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { KnowledgeUpload } from "./KnowledgeUpload";
import { KnowledgeVersionManager } from "./KnowledgeVersionManager";
import {
  flaggedCount,
  isPipelineActive,
  isPublished,
} from "./knowledgePipelineUtils";
import { InlineKnowledgeUploader } from "./InlineKnowledgeUploader";
import { KnowledgeDetailPanel } from "./KnowledgeDetailPanel";
import {
  ALL_PROJECTS,
  useKnowledgeSourceFilters,
} from "./useKnowledgeSourceFilters";
import { ProjectPicker } from "./ProjectPicker";
import { InboxIcons } from "../conversations/InboxIcons";
import { reindexAllKnowledge } from "@/lib/vfic/knowledgeService";
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
  const refresh = useRefresh();
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
  // stop when everything has settled (less visual jitter at rest).
  useEffect(() => {
    if (!sources.some(isPipelineActive)) return;
    const timer = window.setInterval(() => refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh, sources]);

  const hasActive = sources.some(isPipelineActive);
  const hasSources = sources.length > 0;
  const readyCount = sources.filter(isPublished).length;
  const processingCount = sources.filter(isPipelineActive).length;
  const reviewCount = sources.reduce(
    (sum, source) => sum + flaggedCount(source),
    0,
  );
  const unitCount = sources.reduce(
    (sum, source) => sum + (source.digest_meta?.unit_count ?? 0),
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
                  <RefreshCw className="size-3.5 animate-spin" />
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
            <span className="ops-status-label">Đơn vị</span>
            <strong>{unitCount}</strong>
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
          <>
            <SourceSelector
              sources={sources}
              selectedSource={selectedSource}
              total={total}
              onSelect={setSelectedId}
            />
            <ListPagination
              rowsPerPageOptions={[10, 25, 50, 100]}
              className="ops-pagination"
            />
            {selectedSource ? (
              <KnowledgeDetailPanel source={selectedSource} />
            ) : (
              <EmptyState
                icon={<FileText className="size-6" />}
                title="Chọn một nguồn kiến thức"
                description="Chi tiết và thao tác quản lý sẽ hiện ở đây."
                className="min-h-[420px] rounded-[14px] bg-card"
              />
            )}
          </>
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

const SourceSelector = ({
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
  return (
    <section className="knowledge-selector-panel">
      <div className="knowledge-selector-header">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <div className="ops-panel-title">
            <p className="ops-panel-eyebrow">Tài liệu</p>
            <h2>Nguồn kiến thức</h2>
          </div>
          <Badge variant="outline" className="border-border bg-background/70">
            {total} nguồn
          </Badge>
          {selectedSource && (
            <span className="ops-meta-text">
              {selectedSource.project_name ?? "Chưa gắn dự án"} ·{" "}
              {selectedSource.digest_meta?.unit_count ?? 0} đơn vị
            </span>
          )}
        </div>
        <Select
          value={selectedSource ? String(selectedSource.id) : undefined}
          onValueChange={onSelect}
        >
          <SelectTrigger className="h-11 w-full rounded-[9px] border-border bg-background text-control md:w-[380px] lg:w-[460px]">
            <SelectValue placeholder="Chọn nguồn kiến thức" />
          </SelectTrigger>
          <SelectContent className="max-h-96">
            {sources.map((source) => {
              return (
                <SelectItem key={source.id} value={String(source.id)}>
                  <span className="block truncate">
                    {source.file_name} ·{" "}
                    {source.project_name ?? "Chưa gắn dự án"} ·{" "}
                    {source.digest_meta?.unit_count ?? 0} đơn vị
                  </span>
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      </div>
    </section>
  );
};

const SourceSelectorSkeleton = () => (
  <section className="knowledge-selector-skeleton p-4">
    <div className="flex items-center gap-3">
      <Skeleton className="size-10 rounded-[10px]" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-3 w-64 max-w-full" />
      </div>
    </div>
  </section>
);

export const KnowledgeSourceList = () => (
  <ListBase perPage={25} sort={{ field: "updated_at", order: "DESC" }}>
    <KnowledgeSourceListContent />
  </ListBase>
);
