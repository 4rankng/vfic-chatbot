import { useEffect, useRef, useState } from "react";
import { ListBase, useRefresh } from "ra-core";
import { FileText, RefreshCw, Search } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { stageLabel } from "./stageTone";
import { KnowledgeUpload } from "./KnowledgeUpload";
import { isPipelineActive } from "./knowledgePipelineUtils";
import { InlineKnowledgeUploader } from "./InlineKnowledgeUploader";
import { KnowledgeSourceRow } from "./KnowledgeSourceRow";
import { KnowledgeDetailPanel } from "./KnowledgeDetailPanel";
import {
  ALL_PROJECTS,
  ALL_STAGES,
  useKnowledgeSourceFilters,
} from "./useKnowledgeSourceFilters";

const KnowledgeSourceListContent = () => {
  const refresh = useRefresh();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Mobile master-detail: 'list' shows the list, 'detail' shows the detail pane.
  const [mobileView, setMobileView] = useState<"list" | "detail">("list");

  const {
    isPending,
    projects,
    projectById,
    sources,
    stages,
    filteredSources,
    query,
    setQuery,
    projectFilter,
    stageFilter,
    reviewOnly,
    setProjectFilter,
    setStageFilter,
    setReviewOnly,
    selectProject,
  } = useKnowledgeSourceFilters();

  // Keep the selection valid as the filtered list changes; default to the top.
  useEffect(() => {
    if (filteredSources.length === 0) {
      setSelectedId(null);
      return;
    }
    if (
      !selectedId ||
      !filteredSources.some((source) => String(source.id) === selectedId)
    ) {
      setSelectedId(String(filteredSources[0].id));
    }
  }, [filteredSources, selectedId]);

  // Auto-select a source that newly appears mid-session (e.g., right after an
  // upload) so the user immediately sees its progress / extraction.
  const knownIdsRef = useRef<Set<string>>(new Set());
  const firstLoadRef = useRef(true);
  useEffect(() => {
    const ids = new Set(sources.map((source) => String(source.id)));
    if (firstLoadRef.current) {
      knownIdsRef.current = ids;
      firstLoadRef.current = false;
      return;
    }
    const appeared = sources
      .filter((source) => !knownIdsRef.current.has(String(source.id)))
      .map((source) => String(source.id));
    if (appeared.length > 0) setSelectedId(appeared[0]);
    knownIdsRef.current = ids;
  }, [sources]);

  const selectedSource =
    filteredSources.find((source) => String(source.id) === selectedId) ??
    filteredSources[0] ??
    null;

  // Auto-refresh only while something is actively moving through the pipeline;
  // stop when everything has settled (less visual jitter at rest).
  useEffect(() => {
    if (!sources.some(isPipelineActive)) return;
    const timer = window.setInterval(() => refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh, sources]);

  const handleRowSelect = (id: string) => {
    setSelectedId(id);
    setMobileView("detail");
  };

  const hasActive = sources.some(isPipelineActive);

  return (
    <div className="kb-scope min-h-[calc(100vh-4rem)] px-4 py-6 text-foreground md:px-6 lg:py-8">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-5">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 max-w-2xl">
            <p className="kb-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--kb-teal)]">
              Trung tâm kiến thức
            </p>
            <h2 className="kb-display mt-2 text-3xl text-foreground sm:text-[34px]">
              Quản lý kiến thức
            </h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              Theo dõi tài liệu theo từng dự án, trạng thái xử lý, và đánh dấu
              nguồn cần xem lại trước khi agent dùng trong hội thoại.
            </p>
            {hasActive && (
              <p className="kb-mono mt-3 inline-flex items-center gap-2 rounded-[9px] bg-[var(--kb-teal-soft)] px-3 py-1.5 text-[11px] font-medium text-[var(--kb-teal)]">
                <RefreshCw className="size-3.5 animate-spin" />
                Đang xử lý — trang tự làm mới mỗi 5 giây.
              </p>
            )}
          </div>
        </header>

        <KnowledgeUpload open={uploadOpen} onOpenChange={setUploadOpen} />

        <div className="grid gap-2 min-[520px]:grid-cols-[minmax(0,1fr)_150px_150px]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Tìm tài liệu, nguồn, tóm tắt..."
              className="h-10 rounded-[9px] border-border bg-card pl-9 text-sm"
            />
          </div>
          <Select value={projectFilter} onValueChange={selectProject}>
            <SelectTrigger className="h-10 rounded-[9px] border-border bg-card text-sm">
              <SelectValue placeholder="Tất cả dự án" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_PROJECTS}>Tất cả dự án</SelectItem>
              {(projects ?? []).map((project) => (
                <SelectItem key={project.id} value={String(project.id)}>
                  {project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={reviewOnly ? "__review__" : stageFilter}
            onValueChange={(value) => {
              if (value === "__review__") {
                setProjectFilter(ALL_PROJECTS);
                setStageFilter(ALL_STAGES);
                setReviewOnly(true);
                return;
              }
              setReviewOnly(false);
              setStageFilter(value);
            }}
          >
            <SelectTrigger className="h-10 rounded-[9px] border-border bg-card text-sm">
              <SelectValue placeholder="Tất cả giai đoạn" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_STAGES}>Tất cả giai đoạn</SelectItem>
              <SelectItem value="__review__">Cần xem lại</SelectItem>
              {stages.map((stage) => (
                <SelectItem key={stage} value={stage}>
                  {stageLabel(stage)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <section
            className={cn(
              "flex min-h-[460px] flex-col overflow-hidden rounded-[14px] border border-border bg-card",
              mobileView === "detail" && "hidden lg:flex",
            )}
          >
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
              <h3 className="kb-display text-base text-foreground">
                Nguồn kiến thức
              </h3>
              <span className="kb-mono text-xs text-muted-foreground">
                {filteredSources.length}
              </span>
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              {isPending ? (
                <SourceSkeleton />
              ) : sources.length === 0 ? (
                <InlineKnowledgeUploader projects={projects ?? []} />
              ) : filteredSources.length === 0 ? (
                <EmptyState
                  icon={<FileText className="size-6" />}
                  title="Không tìm thấy tài liệu"
                  description="Thử đổi bộ lọc hoặc tải thêm tài liệu cho dự án."
                  className="m-4 bg-card"
                />
              ) : (
                filteredSources.map((source) => (
                  <KnowledgeSourceRow
                    key={source.id}
                    source={source}
                    project={
                      source.project_id
                        ? projectById.get(String(source.project_id))
                        : undefined
                    }
                    selected={selectedSource?.id === source.id}
                    onSelect={() => handleRowSelect(String(source.id))}
                  />
                ))
              )}
            </div>
          </section>

          <div className={cn(mobileView === "list" && "hidden lg:block")}>
            {selectedSource ? (
              <KnowledgeDetailPanel
                source={selectedSource}
                project={
                  selectedSource.project_id
                    ? projectById.get(String(selectedSource.project_id))
                    : undefined
                }
                onBack={() => setMobileView("list")}
              />
            ) : (
              <EmptyState
                icon={<FileText className="size-6" />}
                title="Chọn một nguồn kiến thức"
                description="Chi tiết trích xuất, tóm tắt digest và thao tác quản lý sẽ hiện ở đây."
                className="min-h-[420px] rounded-[14px] bg-card"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

const SourceSkeleton = () => (
  <div className="flex flex-col">
    {Array.from({ length: 6 }).map((_, index) => (
      <div
        key={index}
        className="flex items-start gap-3 border-b border-border p-4"
      >
        <Skeleton className="h-5 w-2/3" />
        <div className="ml-auto flex gap-2">
          <Skeleton className="h-6 w-16 rounded-full" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
      </div>
    ))}
  </div>
);

export const KnowledgeSourceList = () => (
  <ListBase perPage={100} sort={{ field: "updated_at", order: "DESC" }}>
    <KnowledgeSourceListContent />
  </ListBase>
);
