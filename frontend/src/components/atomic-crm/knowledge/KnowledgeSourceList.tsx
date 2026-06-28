import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ListBase,
  useGetList,
  useListContext,
  useNotify,
  useRedirect,
  useRefresh,
} from "ra-core";
import {
  Activity,
  AlertTriangle,
  Archive,
  BookOpen,
  CheckCircle2,
  CircleDashed,
  FileText,
  HelpCircle,
  MoreHorizontal,
  Pencil,
  Quote,
  RefreshCw,
  Search,
  Tags,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { DeleteButton } from "@/components/admin";
import {
  archiveKnowledge,
  getKnowledgeUnits,
  reindexKnowledge,
  type KnowledgeUnit,
} from "@/lib/vfic/knowledgeService";
import { cn } from "@/lib/utils";
import { getRelativeTimeString } from "../leads/leadUtils";
import type { KnowledgeSource, Project } from "../types";
import { stageLabel } from "./stageTone";
import { KnowledgeUpload } from "./KnowledgeUpload";

const ALL_PROJECTS = "__all__";
const ALL_STAGES = "__all__";
const UNASSIGNED_PROJECT = "__unassigned__";

const PIPELINE_STEPS = [
  {
    key: "UPLOADED",
    label: "Đã nhận tệp",
    description: "File đã vào hệ thống và chờ trích văn bản.",
  },
  {
    key: "EXTRACTED",
    label: "Trích văn bản",
    description: "Nội dung đã được đọc từ PDF, Office, CSV hoặc TXT.",
  },
  {
    key: "DIGESTING",
    label: "Digest",
    description: "LLM đang tóm tắt, chia đơn vị và gắn cờ nội dung cần xem.",
  },
  {
    key: "EMBEDDING",
    label: "Vector",
    description: "Các đơn vị kiến thức đang được nhúng để tìm kiếm ngữ nghĩa.",
  },
  {
    key: "INDEXING",
    label: "Lập chỉ mục",
    description: "Nguồn đang được ghi vào kho truy xuất của agent.",
  },
  {
    key: "PUBLISHED",
    label: "Sẵn sàng",
    description: "Agent có thể dùng nguồn này để trả lời.",
  },
] as const;

const flaggedCount = (source: KnowledgeSource): number =>
  source.digest_meta?.flagged_unit_indexes?.length ?? 0;

const sourceStage = (source: KnowledgeSource) =>
  source.stage ?? source.status ?? "UNKNOWN";

const isPublished = (source: KnowledgeSource) =>
  ["PUBLISHED", "READY"].includes(sourceStage(source).toUpperCase()) ||
  ["published", "ready"].includes(source.status?.toLowerCase());

const isFailed = (source: KnowledgeSource) =>
  ["FAILED", "ERROR"].includes(sourceStage(source).toUpperCase()) ||
  ["failed", "error"].includes(source.status?.toLowerCase());

const isRunning = (source: KnowledgeSource) =>
  ["DIGESTING", "EMBEDDING", "INDEXING", "PROCESSING"].includes(
    sourceStage(source).toUpperCase(),
  );

const isPipelineActive = (source: KnowledgeSource) =>
  [
    "UPLOADED",
    "EXTRACTED",
    "DIGESTING",
    "EMBEDDING",
    "INDEXING",
    "PROCESSING",
  ].includes(sourceStage(source).toUpperCase());

const isWaitingForWorker = (source: KnowledgeSource) =>
  ["UPLOADED", "EXTRACTED"].includes(sourceStage(source).toUpperCase());

const needsReview = (source: KnowledgeSource) =>
  flaggedCount(source) > 0 || isFailed(source);

const sourceSearchText = (source: KnowledgeSource, projectName?: string) =>
  [
    source.file_name,
    source.source,
    source.mime_type,
    source.digest_summary,
    sourceStage(source),
    projectName,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

const pipelineStepIndex = (source: KnowledgeSource) => {
  const stage = sourceStage(source).toUpperCase();
  if (stage === "READY") return PIPELINE_STEPS.length - 1;
  if (stage === "PROCESSING") return 2;
  const index = PIPELINE_STEPS.findIndex((step) => step.key === stage);
  return index >= 0 ? index : 0;
};

const pipelinePercent = (source: KnowledgeSource) => {
  if (isFailed(source)) return 100;
  if (isPublished(source)) return 100;
  return Math.max(
    12,
    Math.round((pipelineStepIndex(source) / (PIPELINE_STEPS.length - 1)) * 100),
  );
};

const pipelineStateCopy = (source: KnowledgeSource) => {
  if (isFailed(source)) {
    return "Pipeline dừng vì lỗi. Hãy huấn luyện lại sau khi kiểm tra định dạng hoặc nội dung nguồn.";
  }
  if (isPublished(source)) {
    return "Nguồn đã được xuất bản và agent có thể truy xuất khi trả lời.";
  }
  if (needsReview(source)) {
    return "Nguồn đã chạy xong nhưng có nội dung cần rà soát trước khi tin cậy hoàn toàn.";
  }
  if (isWaitingForWorker(source)) {
    return "Nguồn đã trích văn bản và đang chờ worker ingest nhận việc. Nếu đứng ở đây lâu, hãy kiểm tra tiến trình rq worker ingest.";
  }
  const current = PIPELINE_STEPS[pipelineStepIndex(source)];
  return current?.description ?? "Nguồn đang được xử lý trong pipeline.";
};

const minutesSinceUpdate = (source: KnowledgeSource) => {
  const time = new Date(source.updated_at ?? source.created_at).getTime();
  if (Number.isNaN(time)) return 0;
  return Math.max(0, Math.floor((Date.now() - time) / 60000));
};

const isPossiblyStuck = (source: KnowledgeSource) =>
  isWaitingForWorker(source) && minutesSinceUpdate(source) >= 2;

const isProcessing = (source: KnowledgeSource) =>
  isPipelineActive(source) && !isFailed(source);

const KnowledgeSourceListContent = () => {
  const { data, isPending } = useListContext<KnowledgeSource>();
  const refresh = useRefresh();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [projectFilter, setProjectFilter] = useState(ALL_PROJECTS);
  const [stageFilter, setStageFilter] = useState(ALL_STAGES);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Mobile master-detail: 'list' shows the list, 'detail' shows the detail pane.
  const [mobileView, setMobileView] = useState<"list" | "detail">("list");

  const { data: projects } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
  });

  const projectById = useMemo(() => {
    const map = new Map<string, Project>();
    for (const project of projects ?? []) map.set(String(project.id), project);
    return map;
  }, [projects]);

  const sources = useMemo(() => data ?? [], [data]);
  const stages = useMemo(
    () => Array.from(new Set(sources.map(sourceStage))).sort(),
    [sources],
  );

  const filteredSources = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return sources.filter((source) => {
      const projectId = source.project_id ?? UNASSIGNED_PROJECT;
      if (projectFilter !== ALL_PROJECTS && projectFilter !== projectId)
        return false;
      if (stageFilter !== ALL_STAGES && stageFilter !== sourceStage(source))
        return false;
      if (reviewOnly && !needsReview(source)) return false;
      if (!needle) return true;
      return sourceSearchText(
        source,
        source.project_id
          ? projectById.get(String(source.project_id))?.name
          : "Nguồn chung",
      ).includes(needle);
    });
  }, [projectById, projectFilter, query, reviewOnly, sources, stageFilter]);

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

  const selectProject = (projectId: string) => {
    setProjectFilter(projectId);
    setStageFilter(ALL_STAGES);
    setReviewOnly(false);
  };

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
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refresh()}
              className="h-10 rounded-[9px]"
            >
              <RefreshCw className="size-4" />
              Làm mới
            </Button>
            <Button
              size="sm"
              onClick={() => setUploadOpen(true)}
              className="h-10 rounded-[9px]"
            >
              <Upload className="size-4" />
              Tải lên
            </Button>
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
              <SelectItem value={UNASSIGNED_PROJECT}>Nguồn chung</SelectItem>
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
                <EmptyState
                  icon={<BookOpen className="size-6" />}
                  title="Chưa có cơ sở kiến thức"
                  description="Tải lên PDF, DOCX, XLSX, CSV, TXT hoặc dán tin tuyển dụng để huấn luyện agent."
                  actions={
                    <Button size="sm" onClick={() => setUploadOpen(true)}>
                      <Upload className="size-4" />
                      Tải lên
                    </Button>
                  }
                  className="m-4 bg-card"
                />
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

const KnowledgeSourceRow = ({
  source,
  project,
  selected,
  onSelect,
}: {
  source: KnowledgeSource;
  project?: Project;
  selected: boolean;
  onSelect: () => void;
}) => {
  const flags = flaggedCount(source);
  const processing = isProcessing(source);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect();
      }}
      className={cn(
        "group flex gap-3 border-b border-border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "bg-[var(--kb-teal-soft)] shadow-[inset_2.5px_0_0_0_var(--kb-teal)]"
          : "hover:bg-secondary",
      )}
    >
      <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="break-words text-[13.5px] font-semibold text-foreground">
              {source.file_name}
            </div>
            <div className="kb-mono mt-1 break-words text-[11.5px] text-muted-foreground">
              {project?.name ?? "Nguồn chung"} ·{" "}
              {getRelativeTimeString(source.updated_at ?? source.created_at)} ·{" "}
              {source.digest_meta?.unit_count ?? 0} đơn vị
            </div>
          </div>
          <div className="shrink-0 pt-0.5">
            <SourceStamp source={source} />
          </div>
        </div>

        {processing && (
          <div className="mt-3">
            <PipelineMiniProgress source={source} />
          </div>
        )}

        <div
          className="mt-2 flex flex-wrap items-center gap-2"
          onClick={(event) => event.stopPropagation()}
        >
          {flags > 0 && <Chip tone="warning">{flags} cần xem lại</Chip>}
          <div className="ml-auto">
            <SourceRowActions source={source} />
          </div>
        </div>
      </div>
    </div>
  );
};

const Stamp = ({
  tone,
  icon,
  children,
}: {
  tone: "ready" | "error" | "pending" | "processing";
  icon?: ReactNode;
  children: ReactNode;
}) => (
  <span
    className={cn(
      "kb-stamp",
      tone === "ready" && "text-[var(--kb-teal)]",
      tone === "error" && "text-[var(--kb-rust)]",
      tone === "pending" && "kb-stamp--pending text-[var(--kb-ochre)]",
      tone === "processing" && "text-[var(--kb-teal)]",
    )}
  >
    {icon}
    {children}
  </span>
);

const SourceStamp = ({ source }: { source: KnowledgeSource }) => {
  if (isFailed(source))
    return (
      <Stamp tone="error" icon={<AlertTriangle className="size-3" />}>
        Lỗi
      </Stamp>
    );
  if (isPossiblyStuck(source))
    return (
      <Stamp tone="pending" icon={<RefreshCw className="size-3" />}>
        Chờ worker
      </Stamp>
    );
  if (isRunning(source))
    return (
      <Stamp
        tone="processing"
        icon={<RefreshCw className="size-3 animate-spin" />}
      >
        Đang xử lý
      </Stamp>
    );
  if (isPublished(source))
    return (
      <Stamp tone="ready" icon={<CheckCircle2 className="size-3" />}>
        Sẵn sàng
      </Stamp>
    );
  if (needsReview(source)) return <Stamp tone="pending">Cần xem lại</Stamp>;
  return <Stamp tone="pending">{stageLabel(sourceStage(source))}</Stamp>;
};

// Slim transient progress — only mounted while a source is actively processing.
const PipelineMiniProgress = ({ source }: { source: KnowledgeSource }) => {
  const percent = pipelinePercent(source);
  return (
    <div className="min-w-0">
      <div className="kb-mono flex items-center justify-between gap-2 text-[11px]">
        <span className="font-semibold text-[var(--kb-teal)]">
          {isPossiblyStuck(source)
            ? "Đang chờ worker"
            : isPublished(source)
              ? "Sẵn sàng trả lời"
              : stageLabel(sourceStage(source))}
        </span>
        <span className="text-muted-foreground">{percent}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--kb-line-strong)]/40">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            isFailed(source)
              ? "bg-[var(--kb-rust)]"
              : "bg-[var(--kb-teal)]",
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
};

const Chip = ({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "processing";
}) => (
  <span
    className={cn(
      "kb-mono rounded-full px-2 py-1 text-[11px] font-semibold leading-none",
      tone === "neutral" && "bg-secondary text-[var(--kb-ink-700)]",
      tone === "success" && "bg-[var(--kb-teal-soft)] text-[var(--kb-teal)]",
      tone === "warning" && "bg-[var(--kb-ochre-soft)] text-[var(--kb-ochre)]",
      tone === "danger" && "bg-[var(--kb-rust-soft)] text-[var(--kb-rust)]",
      tone === "processing" && "bg-[var(--kb-teal-soft)] text-[var(--kb-teal)]",
    )}
  >
    {children}
  </span>
);

const SourceRowActions = ({ source }: { source: KnowledgeSource }) => {
  const redirect = useRedirect();
  const refresh = useRefresh();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 rounded-lg text-muted-foreground opacity-70 transition-opacity hover:opacity-100"
          aria-label={`Mở thao tác cho ${source.file_name}`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuItem
          onSelect={() => redirect("edit", "knowledge_sources", source.id)}
        >
          <Pencil className="size-4" />
          Sửa
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DeleteButton
          record={source}
          resource="knowledge_sources"
          label="Xóa"
          size="sm"
          variant="ghost"
          redirect={false}
          successMessage="Đã xóa tài liệu."
          mutationOptions={{ onSuccess: () => refresh() }}
          className="h-8 w-full justify-start px-2 text-sm text-destructive hover:bg-destructive/10"
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

const KnowledgeDetailPanel = ({
  source,
  project,
  onBack,
}: {
  source: KnowledgeSource;
  project?: Project;
  onBack: () => void;
}) => {
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();
  const flags = flaggedCount(source);
  const [showPipeline, setShowPipeline] = useState(false);
  const processing = isProcessing(source);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      notify(ok, { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <section className="flex min-h-[620px] flex-col gap-4 rounded-[14px] border border-border bg-card p-5 text-foreground lg:p-6">
      <button
        type="button"
        onClick={onBack}
        className="kb-mono self-start rounded-[9px] px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground lg:hidden"
      >
        ← Quay lại danh sách
      </button>

      {/* Compact identity — one block, no duplicated stats */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="kb-display break-words text-xl text-foreground">
            {source.file_name}
          </h3>
          <p className="kb-mono mt-1 break-words text-[12.5px] text-muted-foreground">
            {project?.name ?? "Nguồn chung"} · {source.mime_type || "Tài liệu"}{" "}
            · Cập nhật{" "}
            {getRelativeTimeString(source.updated_at ?? source.created_at)}
          </p>
        </div>
        <div className="shrink-0 pt-0.5">
          <SourceStamp source={source} />
        </div>
      </div>

      {/* Single, context-dependent action row */}
      <div className="flex flex-wrap gap-2 border-b border-border pb-4">
        <Button
          size="sm"
          onClick={() => redirect("edit", "knowledge_sources", source.id)}
          className="rounded-[9px]"
        >
          <Pencil className="size-4" />
          Sửa
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            run(
              () => reindexKnowledge(String(source.id)),
              "Đã đưa vào hàng huấn luyện lại.",
            )
          }
          className="rounded-[9px]"
        >
          <RefreshCw className="size-4" />
          Huấn luyện lại
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              className="rounded-[9px]"
              aria-label={`Mở thao tác cho ${source.file_name}`}
            >
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem
              onSelect={() =>
                run(
                  () => archiveKnowledge(String(source.id)),
                  "Đã lưu trữ. Agent sẽ không dùng nguồn này nữa.",
                )
              }
            >
              <Archive className="size-4" />
              Lưu trữ
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DeleteButton
              record={source}
              resource="knowledge_sources"
              label="Xóa"
              size="sm"
              variant="ghost"
              redirect={false}
              successMessage="Đã xóa tài liệu."
              mutationOptions={{ onSuccess: () => refresh() }}
              className="h-8 w-full justify-start px-2 text-sm text-destructive hover:bg-destructive/10"
            />
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {processing && <PipelineMiniProgress source={source} />}

      {source.error && (
        <div className="rounded-[10px] border border-[var(--kb-rust-soft)] bg-[var(--kb-rust-soft)] p-3 text-sm text-[var(--kb-rust)]">
          {source.error}
        </div>
      )}

      {/* Compact stat trio (units / flagged / updated) — hairline grid */}
      <div className="grid grid-cols-3 gap-px overflow-hidden rounded-[10px] bg-border">
        <InfoBlock
          label="Đơn vị"
          value={String(source.digest_meta?.unit_count ?? 0)}
        />
        <InfoBlock label="Cần xem lại" value={String(flags)} />
        <InfoBlock
          label="Cập nhật"
          value={getRelativeTimeString(source.updated_at ?? source.created_at)}
        />
      </div>

      {/* Digest ticket */}
      <div>
        <h4 className="kb-display text-sm text-foreground">Tóm tắt digest</h4>
        {source.digest_summary ? (
          <div className="mt-2 rounded-[10px] border border-dashed border-[var(--kb-line-strong)] bg-background p-4">
            <p
              className="text-[13.5px] italic text-[var(--kb-ink-700)]"
              style={{ fontFamily: "var(--kb-font-display)" }}
            >
              {source.digest_summary}
            </p>
          </div>
        ) : (
          <PipelineDigestHint source={source} />
        )}
      </div>

      {/* Extracted knowledge units — the star */}
      <StoredKnowledgePanel source={source} />

      {/* Pipeline detail — collapsed, demoted */}
      <div>
        <button
          type="button"
          onClick={() => setShowPipeline((value) => !value)}
          className="flex w-full items-center justify-between gap-2 rounded-[10px] border border-border bg-background px-4 py-3 text-left text-sm font-semibold text-foreground transition-colors hover:bg-secondary"
        >
          <span>Chi tiết pipeline (6 bước)</span>
          <span className="kb-mono text-xs text-muted-foreground">
            {pipelinePercent(source)}% ·{" "}
            {isFailed(source)
              ? "Lỗi"
              : isPublished(source)
                ? "Sẵn sàng"
                : stageLabel(sourceStage(source))}
          </span>
        </button>
        {showPipeline && (
          <div className="mt-2 rounded-[10px] border border-border bg-background p-4">
            <p className="mb-3 text-xs leading-5 text-muted-foreground">
              {pipelineStateCopy(source)}
            </p>
            <PipelineTimeline source={source} />
          </div>
        )}
      </div>
    </section>
  );
};

const InfoBlock = ({ label, value }: { label: string; value: string }) => (
  <div className="min-w-0 bg-card px-4 py-3">
    <div className="kb-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
      {label}
    </div>
    <div className="kb-mono mt-1.5 break-words text-lg font-semibold text-foreground">
      {value}
    </div>
  </div>
);

const StoredKnowledgePanel = ({ source }: { source: KnowledgeSource }) => {
  const { data, isError, isPending } = useQuery({
    queryKey: ["knowledge-units", source.id],
    queryFn: () => getKnowledgeUnits(String(source.id), 50),
    enabled: Boolean(source.id) && (isPublished(source) || needsReview(source)),
    staleTime: 5000,
  });
  const units = data?.data ?? [];

  return (
    <section className="rounded-[12px] border border-border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="kb-display text-sm text-foreground">Kiến thức đã lưu</h4>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Đơn vị agent thực sự truy xuất — đây là phần con người có thể kiểm
            tra.
          </p>
        </div>
        <Badge className="kb-mono rounded-full bg-secondary text-[11px] text-[var(--kb-ink-700)] hover:bg-secondary">
          {source.digest_meta?.unit_count ?? units.length} đơn vị
        </Badge>
      </div>

      {!isPublished(source) && !needsReview(source) ? (
        <div className="mt-3 flex items-center gap-2 rounded-[10px] bg-[var(--kb-teal-soft)] p-3 text-sm text-[var(--kb-teal)]">
          <RefreshCw className="size-4 animate-spin" />
          Kiến thức sẽ hiện ở đây sau khi pipeline xuất bản các đơn vị truy xuất.
        </div>
      ) : isPending ? (
        <div className="mt-4 grid gap-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-24 rounded-[10px]" />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-3 rounded-[10px] bg-[var(--kb-rust-soft)] p-3 text-sm text-[var(--kb-rust)]">
          Chưa tải được danh sách kiến thức đã lưu. Hãy làm mới trang hoặc thử
          lại sau.
        </div>
      ) : units.length === 0 ? (
        <div className="mt-3 rounded-[10px] bg-secondary p-3 text-sm text-muted-foreground">
          Chưa có đơn vị kiến thức nào được lưu. Nếu tài liệu đã xử lý xong, hãy
          kiểm tra nội dung nguồn hoặc chạy lại pipeline.
        </div>
      ) : (
        <div className="mt-4 grid max-h-[460px] gap-3 overflow-y-auto pr-1">
          {units.map((unit) => (
            <KnowledgeUnitCard key={unit.id} unit={unit} />
          ))}
        </div>
      )}
    </section>
  );
};

const KnowledgeUnitCard = ({ unit }: { unit: KnowledgeUnit }) => {
  const questionCount = unit.questions?.length ?? 0;
  const entityEntries = Object.entries(unit.entities ?? {}).filter(
    ([, value]) =>
      value !== null && value !== undefined && String(value) !== "",
  );

  return (
    <article className="rounded-[10px] border border-border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip>{unit.category || "other"}</Chip>
        <Chip
          tone={
            unit.confidence === "low"
              ? "warning"
              : unit.confidence === "high"
                ? "success"
                : "neutral"
          }
        >
          Tin cậy {unit.confidence || "medium"}
        </Chip>
        {unit.is_inference && <Chip tone="warning">Suy luận</Chip>}
        <span className="kb-mono ml-auto text-[11px] text-muted-foreground">
          #{unit.chunk_index + 1}
        </span>
      </div>

      <p className="mt-3 break-words text-sm leading-6 text-foreground">
        {unit.content}
      </p>

      {unit.summary && (
        <div className="mt-3 rounded-lg bg-secondary p-3 text-xs leading-5 text-muted-foreground">
          {unit.summary}
        </div>
      )}

      {unit.source_quote && (
        <div className="mt-3 flex gap-2 rounded-lg border border-border bg-secondary p-3 text-xs leading-5 text-muted-foreground">
          <Quote className="mt-0.5 size-4 shrink-0 text-[var(--kb-ink-300)]" />
          <span className="break-words">{unit.source_quote}</span>
        </div>
      )}

      {questionCount > 0 && (
        <div className="mt-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <HelpCircle className="size-4 text-[var(--kb-teal)]" />
            Câu hỏi unit này trả lời được
          </div>
          <ul className="mt-2 grid gap-1.5">
            {unit.questions.slice(0, 3).map((question) => (
              <li
                key={question}
                className="break-words rounded-lg bg-secondary px-3 py-2 text-xs leading-5 text-[var(--kb-ink-700)]"
              >
                {question}
              </li>
            ))}
          </ul>
        </div>
      )}

      {entityEntries.length > 0 && (
        <div className="mt-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <Tags className="size-4 text-[var(--kb-teal)]" />
            Thực thể đã nhận diện
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {entityEntries.slice(0, 8).map(([key, value]) => (
              <span
                key={key}
                className="kb-mono rounded-full bg-secondary px-2 py-1 text-[11px] text-[var(--kb-ink-700)]"
              >
                {key}: {String(value)}
              </span>
            ))}
          </div>
        </div>
      )}
    </article>
  );
};

const PipelineTimeline = ({ source }: { source: KnowledgeSource }) => {
  const currentIndex = pipelineStepIndex(source);

  return (
    <ol className="grid gap-2">
      {PIPELINE_STEPS.map((step, index) => {
        const done = isPublished(source) || index < currentIndex;
        const current = !isPublished(source) && index === currentIndex;
        const failedHere = isFailed(source) && index === currentIndex;

        return (
          <li
            key={step.key}
            className={cn(
              "grid grid-cols-[28px_minmax(0,1fr)] gap-3 rounded-[10px] p-2",
              current && !failedHere && "bg-[var(--kb-teal-soft)]",
              failedHere && "bg-[var(--kb-rust-soft)]",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex size-7 items-center justify-center rounded-full",
                done && "bg-[var(--kb-teal)] text-[var(--kb-teal-soft)]",
                current &&
                  !failedHere &&
                  "bg-[var(--kb-teal)] text-[var(--kb-teal-soft)]",
                failedHere && "bg-[var(--kb-rust)] text-white",
                !done &&
                  !current &&
                  !failedHere &&
                  "bg-secondary text-muted-foreground",
              )}
            >
              {failedHere ? (
                <AlertTriangle className="size-4" />
              ) : done ? (
                <CheckCircle2 className="size-4" />
              ) : current ? (
                <Activity className="size-4" />
              ) : (
                <CircleDashed className="size-4" />
              )}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-foreground">
                {step.label}
              </span>
              <span className="mt-0.5 block break-words text-xs leading-5 text-muted-foreground">
                {step.description}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
};

const PipelineDigestHint = ({ source }: { source: KnowledgeSource }) => {
  if (isRunning(source)) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-[10px] bg-[var(--kb-teal-soft)] p-3 text-sm text-[var(--kb-teal)]">
        <RefreshCw className="size-4 animate-spin" />
        Đang xử lý trong pipeline. Tóm tắt sẽ xuất hiện sau khi digest hoàn tất.
      </div>
    );
  }

  if (isFailed(source)) {
    return (
      <div className="mt-2 rounded-[10px] bg-[var(--kb-rust-soft)] p-3 text-sm text-[var(--kb-rust)]">
        Pipeline đã lỗi trước khi tạo tóm tắt. Huấn luyện lại hoặc kiểm tra định
        dạng nguồn nếu lỗi lặp lại.
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-[10px] border border-dashed border-[var(--kb-line-strong)] bg-background p-4">
      <p
        className="text-[13.5px] italic text-[var(--kb-ink-300)]"
        style={{ fontFamily: "var(--kb-font-display)" }}
      >
        Pipeline chưa trả về tóm tắt cho nguồn này. Tóm tắt sẽ hiện ra ở đây sau
        khi digest xử lý xong.
      </p>
    </div>
  );
};

export const KnowledgeSourceList = () => (
  <ListBase perPage={100} sort={{ field: "updated_at", order: "DESC" }}>
    <KnowledgeSourceListContent />
  </ListBase>
);
