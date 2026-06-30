import { useEffect, useRef, useState } from "react";
import { ListBase, useRefresh } from "ra-core";
import { FileText, RefreshCw, Search, Upload } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ListPagination } from "@/components/admin/list-pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { KnowledgeUpload } from "./KnowledgeUpload";
import { isPipelineActive } from "./knowledgePipelineUtils";
import { InlineKnowledgeUploader } from "./InlineKnowledgeUploader";
import { KnowledgeDetailPanel } from "./KnowledgeDetailPanel";
import { ALL_PROJECTS, useKnowledgeSourceFilters } from "./useKnowledgeSourceFilters";

const KnowledgeSourceListContent = () => {
  const refresh = useRefresh();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const {
    isPending,
    projects,
    projectById,
    sources,
    pageSources,
    total,
    query,
    setQuery,
    projectFilter,
    selectProject,
  } = useKnowledgeSourceFilters();

  // Keep the selection valid as the backend page changes; default to the top.
  useEffect(() => {
    if (pageSources.length === 0) {
      setSelectedId(null);
      return;
    }
    if (
      !selectedId ||
      !pageSources.some((source) => String(source.id) === selectedId)
    ) {
      setSelectedId(String(pageSources[0].id));
    }
  }, [pageSources, selectedId]);

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
    pageSources.find((source) => String(source.id) === selectedId) ??
    pageSources[0] ??
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

  return (
    <div className="kb-scope min-h-[calc(100vh-4rem)] px-3 py-5 text-foreground sm:px-4 md:px-6 lg:py-8">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-4 sm:gap-5">
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
          {hasSources && (
            <Button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="h-10 w-full rounded-[9px] sm:w-fit"
            >
              <Upload className="size-4" />
              Thêm tệp
            </Button>
          )}
        </header>

        <KnowledgeUpload
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          initialProjectId={uploadProjectId ? String(uploadProjectId) : undefined}
        />

        <div className="grid gap-2 min-[520px]:grid-cols-[minmax(0,1fr)_180px]">
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
        </div>

        {isPending ? (
          <SourceSelectorSkeleton />
        ) : sources.length === 0 ? (
          <InlineKnowledgeUploader projects={projects ?? []} />
        ) : pageSources.length === 0 ? (
          <EmptyState
            icon={<FileText className="size-6" />}
            title="Không tìm thấy tài liệu"
            description="Thử đổi bộ lọc hoặc tải thêm tài liệu cho dự án."
            actions={
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setUploadOpen(true)}
              >
                <Upload className="size-4" />
                Thêm tệp cho dự án
              </Button>
            }
            className="rounded-[14px] bg-card"
          />
        ) : (
          <>
            <SourceSelector
              sources={pageSources}
              selectedSource={selectedSource}
              projectById={projectById}
              total={total}
              onSelect={setSelectedId}
            />
            <ListPagination
              rowsPerPageOptions={[10, 25, 50, 100]}
              className="justify-center"
            />
            {selectedSource ? (
              <KnowledgeDetailPanel
                source={selectedSource}
                project={
                  selectedSource.project_id
                    ? projectById.get(String(selectedSource.project_id))
                    : undefined
                }
              />
            ) : (
              <EmptyState
                icon={<FileText className="size-6" />}
                title="Chọn một nguồn kiến thức"
                description="Chi tiết trích xuất, tóm tắt digest và thao tác quản lý sẽ hiện ở đây."
                className="min-h-[420px] rounded-[14px] bg-card"
              />
            )}
          </>
        )}
      </div>
    </div>
  );
};

const SourceSelector = ({
  sources,
  selectedSource,
  projectById,
  total,
  onSelect,
}: {
  sources: ReturnType<typeof useKnowledgeSourceFilters>["pageSources"];
  selectedSource: ReturnType<typeof useKnowledgeSourceFilters>["pageSources"][number] | null;
  projectById: ReturnType<typeof useKnowledgeSourceFilters>["projectById"];
  total: number;
  onSelect: (id: string) => void;
}) => {
  const selectedProject = selectedSource?.project_id
    ? projectById.get(String(selectedSource.project_id))
    : undefined;

  return (
    <section className="border-y border-border py-3 sm:rounded-[14px] sm:border sm:bg-card sm:p-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <h3 className="kb-display text-base text-foreground">
            Nguồn đang xem
          </h3>
          <Badge variant="secondary" className="rounded-[8px]">
            {total} nguồn
          </Badge>
          {selectedSource && (
            <span className="kb-mono truncate text-xs text-muted-foreground">
              {selectedProject?.name ?? "Chưa gắn dự án"} ·{" "}
              {selectedSource.digest_meta?.unit_count ?? 0} đơn vị
            </span>
          )}
        </div>
        <Select
          value={selectedSource ? String(selectedSource.id) : undefined}
          onValueChange={onSelect}
        >
          <SelectTrigger className="h-10 w-full rounded-[9px] border-border bg-background text-sm md:w-[360px] lg:w-[420px]">
            <SelectValue placeholder="Chọn nguồn kiến thức" />
          </SelectTrigger>
          <SelectContent className="max-h-96">
            {sources.map((source) => {
              const project = source.project_id
                ? projectById.get(String(source.project_id))
                : undefined;
              return (
                <SelectItem key={source.id} value={String(source.id)}>
                  <span className="block truncate">
                    {source.file_name} · {project?.name ?? "Chưa gắn dự án"} ·{" "}
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
  <section className="rounded-[14px] border border-border bg-card p-4">
    <Skeleton className="h-4 w-32" />
    <Skeleton className="mt-3 h-11 w-full" />
  </section>
);

export const KnowledgeSourceList = () => (
  <ListBase perPage={25} sort={{ field: "updated_at", order: "DESC" }}>
    <KnowledgeSourceListContent />
  </ListBase>
);
