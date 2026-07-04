import { useEffect, useState } from "react";
import { ListBase, useRefresh } from "ra-core";
import { useMasterDetailSelection } from "../hooks/useMasterDetailSelection";
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
import {
  ALL_PROJECTS,
  useKnowledgeSourceFilters,
} from "./useKnowledgeSourceFilters";
import { ProjectPicker } from "./ProjectPicker";
import type { KnowledgeSource } from "../types";

const KnowledgeSourceListContent = () => {
  const refresh = useRefresh();
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

  return (
    <div className="kb-scope min-h-[calc(100vh-4rem)] px-3 py-5 text-foreground sm:px-4 md:px-6 lg:py-8">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-4 sm:gap-5">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 max-w-2xl">
            <p className="kb-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--kb-teal)]">
              Trung tâm kiến thức
            </p>
            <h1 className="kb-display mt-2 text-3xl text-foreground sm:text-[34px]">
              Quản lý kiến thức
            </h1>
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
          initialProjectId={
            uploadProjectId ? String(uploadProjectId) : undefined
          }
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
          <div className="flex gap-2">
            <ProjectPicker
              value={projectFilter === ALL_PROJECTS ? "" : projectFilter}
              onChange={selectProject}
            />
            {projectFilter !== ALL_PROJECTS && (
              <Button
                type="button"
                variant="outline"
                onClick={() => selectProject(ALL_PROJECTS)}
                className="h-10 rounded-[9px]"
              >
                Tất cả
              </Button>
            )}
          </div>
        </div>

        {isPending ? (
          <SourceSelectorSkeleton />
        ) : sources.length === 0 ? (
          <InlineKnowledgeUploader />
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
              className="justify-center"
            />
            {selectedSource ? (
              <KnowledgeDetailPanel source={selectedSource} />
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
    <section className="border-y border-border py-3 sm:rounded-[14px] sm:border sm:bg-card sm:p-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <h2 className="kb-display text-base text-foreground">
            Nguồn đang xem
          </h2>
          <Badge variant="secondary" className="rounded-[8px]">
            {total} nguồn
          </Badge>
          {selectedSource && (
            <span className="kb-mono truncate text-xs text-muted-foreground">
              {selectedSource.project_name ?? "Chưa gắn dự án"} ·{" "}
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
