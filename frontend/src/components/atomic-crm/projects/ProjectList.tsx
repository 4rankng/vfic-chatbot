import { useEffect, useMemo, useState } from "react";
import {
  ListBase,
  useGetList,
  useListContext,
  useNotify,
  usePermissions,
  useRedirect,
  useRefresh,
} from "ra-core";
import {
  Activity,
  Boxes,
  ChevronDown,
  FileText,
  MapPin,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Star,
  Upload,
} from "lucide-react";
import { DeleteButton } from "@/components/admin";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { cn } from "@/lib/utils";
import { TopToolbar } from "../layout/TopToolbar";
import type { KnowledgeSource, Project } from "../types";
import { reindexKnowledge, reindexProject } from "@/lib/vfic/knowledgeService";
import { KnowledgeUpload } from "../knowledge/KnowledgeUpload";
import { stageLabel, stageTone } from "../knowledge/stageTone";
import { ProjectFeatures } from "./ProjectFeatures";

const getProjectLocation = (project: Project) =>
  project.index_card?.location?.trim() || "Chưa có địa điểm";

const getProjectHighlights = (project: Project) =>
  project.index_card?.highlights?.filter(Boolean) ?? [];

const isFailedSource = (source: KnowledgeSource) =>
  String(source.status ?? source.stage ?? "").toUpperCase() === "FAILED";

const ProjectListContent = () => {
  const { data, isPending } = useListContext<Project>();
  const { permissions } = usePermissions();
  const isAdmin = permissions === "admin";
  const refresh = useRefresh();
  const redirect = useRedirect();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  const { data: knowledgeSources } = useGetList<KnowledgeSource>(
    "knowledge_sources",
    {
      pagination: { page: 1, perPage: 250 },
      sort: { field: "updated_at", order: "DESC" },
    },
  );

  const projects = useMemo(() => data ?? [], [data]);
  const projectDocs = useMemo(() => {
    const counts = new Map<string, KnowledgeSource[]>();
    for (const source of knowledgeSources ?? []) {
      if (!source.project_id) continue;
      const projectId = String(source.project_id);
      counts.set(projectId, [...(counts.get(projectId) ?? []), source]);
    }
    return counts;
  }, [knowledgeSources]);

  const filteredProjects = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.filter((project) => {
      if (!needle) return true;
      const haystack = [
        project.name,
        project.slug,
        project.summary,
        project.index_card?.location,
        ...(project.index_card?.key_roles ?? []),
        ...getProjectHighlights(project),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [projects, query]);

  useEffect(() => {
    if (filteredProjects.length === 0) {
      setSelectedId(null);
      return;
    }
    if (
      !selectedId ||
      !filteredProjects.some((project) => project.id === selectedId)
    ) {
      setSelectedId(String(filteredProjects[0].id));
    }
  }, [filteredProjects, selectedId]);

  const selectedProject =
    filteredProjects.find((project) => project.id === selectedId) ??
    filteredProjects[0] ??
    null;
  const activeCount = projects.filter((project) => project.is_active).length;
  const totalDocs = knowledgeSources?.length ?? 0;
  const projectWithDocs = projects.filter(
    (project) => (projectDocs.get(String(project.id)) ?? []).length > 0,
  ).length;

  return (
    <div className="min-h-[calc(100vh-7rem)] pb-24 md:pb-0">
      <TopToolbar className="flex-wrap items-start gap-3">
        <div className="mr-auto min-w-0">
          <h2 className="text-2xl font-bold tracking-tight md:text-3xl">
            Quản lý dự án
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Theo dõi product card, nguồn kiến thức và 16 đặc điểm sản phẩm mà
            agent dùng khi tư vấn ứng viên.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refresh()}>
          <RefreshCw className="size-4" />
        </Button>
        {isAdmin && (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setUploadOpen(true)}
            >
              <Upload className="size-4" />
              Tải kiến thức
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => redirect("create", "projects")}
            >
              <Plus className="size-4" />
              Tạo dự án
            </Button>
          </>
        )}
      </TopToolbar>

      <StatsRibbon
        stats={[
          {
            icon: <Boxes className="size-4" />,
            label: "Dự án",
            value: String(projects.length),
            detail: `${activeCount} đang hoạt động`,
          },
          {
            icon: <Activity className="size-4" />,
            label: "Tỷ lệ bật",
            value: projects.length
              ? `${Math.round((activeCount / projects.length) * 100)}%`
              : "0%",
            detail: "Agent ưu tiên dự án đang hoạt động",
            progress: projects.length
              ? Math.round((activeCount / projects.length) * 100)
              : 0,
          },
          {
            icon: <FileText className="size-4" />,
            label: "Nguồn kiến thức",
            value: String(totalDocs),
            detail: `${projectWithDocs} dự án có tài liệu`,
          },
          {
            icon: <Star className="size-4" />,
            label: "Product cards",
            value: String(projects.filter((project) => project.summary).length),
            detail: "Có tóm tắt / thẻ danh mục",
          },
        ]}
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(360px,0.9fr)_minmax(0,1.4fr)]">
        <Card className="overflow-hidden">
          <CardHeader className="gap-3 border-b">
            <CardTitle className="text-base">Danh mục dự án</CardTitle>
            <div className="flex flex-col gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Tìm theo tên, slug, vị trí..."
                  className="pl-9"
                />
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {isPending ? (
              <ProjectSkeleton />
            ) : filteredProjects.length === 0 ? (
              <EmptyState
                icon={<Boxes className="size-6" />}
                title="Không tìm thấy dự án"
                description="Thử đổi bộ lọc hoặc tạo dự án mới để agent có product context."
                className="m-4"
              />
            ) : (
              <div className="max-h-[calc(100vh-300px)] min-h-[420px] overflow-y-auto">
                {filteredProjects.map((project) => (
                  <ProjectManagementRow
                    key={project.id}
                    project={project}
                    selected={selectedProject?.id === project.id}
                    onSelect={() => setSelectedId(String(project.id))}
                    isAdmin={isAdmin}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {selectedProject ? (
          <ProjectDetailPanel
            project={selectedProject}
            docs={projectDocs.get(String(selectedProject.id)) ?? []}
            isAdmin={isAdmin}
            onUpload={() => setUploadOpen(true)}
          />
        ) : (
          <EmptyState
            icon={<Boxes className="size-6" />}
            title="Chọn một dự án"
            description="Thông tin product card, nguồn kiến thức và đặc điểm sản phẩm sẽ hiện ở đây."
            className="min-h-[420px]"
          />
        )}
      </div>

      {isAdmin && (
        <KnowledgeUpload open={uploadOpen} onOpenChange={setUploadOpen} />
      )}
    </div>
  );
};

// Circumference of the StatsRibbon progress ring (r=15 in a 36×36 viewBox).
const RING_CIRCUMFERENCE = 2 * Math.PI * 15;

// Shared readiness ring: reuses the exact SVG ring math from StatsRibbon
// (viewBox 0 0 36 36, r=15, -rotate-90, primary stroke over border track).
// Renders a muted dash when readiness is undefined (e.g. older API response).
const ReadinessRing = ({
  ready,
  total,
  size = "size-9",
}: {
  ready: number | undefined;
  total: number;
  size?: string;
}) => {
  const known = typeof ready === "number";
  const pct = known ? Math.max(0, Math.min(100, (ready as number) / total)) : 0;
  const dash = pct * RING_CIRCUMFERENCE;
  return (
    <svg
      viewBox="0 0 36 36"
      className={cn(size, "shrink-0 -rotate-90")}
      role="img"
      aria-label={
        known
          ? `${ready}/${total} có thể tư vấn`
          : "Chưa có dữ liệu sẵn sàng tư vấn"
      }
    >
      <circle
        cx="18"
        cy="18"
        r="15"
        fill="none"
        strokeWidth="3.5"
        stroke="var(--border)"
      />
      <circle
        cx="18"
        cy="18"
        r="15"
        fill="none"
        strokeWidth="3.5"
        strokeLinecap="round"
        stroke="var(--primary)"
        strokeDasharray={
          known
            ? `${dash} ${RING_CIRCUMFERENCE}`
            : `${RING_CIRCUMFERENCE / 8} ${RING_CIRCUMFERENCE / 4}`
        }
        className={cn("transition-all duration-500", !known && "opacity-40")}
      />
    </svg>
  );
};

const StatsRibbon = ({
  stats,
}: {
  stats: {
    icon: React.ReactNode;
    label: string;
    value: string;
    detail: string;
    /** Optional 0–100; when present, an SVG ring replaces the icon tile. */
    progress?: number;
  }[];
}) => (
  <div className="mt-4 grid overflow-hidden rounded-lg border bg-card/80 shadow-sm backdrop-blur-[1px] sm:grid-cols-2 lg:grid-cols-4">
    {stats.map((stat) => {
      const hasRing = typeof stat.progress === "number";
      const dash = hasRing
        ? (Math.max(0, Math.min(100, stat.progress as number)) / 100) *
          RING_CIRCUMFERENCE
        : 0;
      return (
        <div
          key={stat.label}
          className="flex min-h-12 items-center gap-3 border-b px-4 py-2 last:border-b-0 sm:[&:nth-child(2n)]:border-l lg:border-b-0 lg:border-l lg:first:border-l-0"
        >
          {hasRing ? (
            <svg
              viewBox="0 0 36 36"
              className="size-9 shrink-0 -rotate-90"
              aria-hidden="true"
            >
              <circle
                cx="18"
                cy="18"
                r="15"
                fill="none"
                strokeWidth="3.5"
                stroke="var(--border)"
              />
              <circle
                cx="18"
                cy="18"
                r="15"
                fill="none"
                strokeWidth="3.5"
                strokeLinecap="round"
                stroke="var(--primary)"
                strokeDasharray={`${dash} ${RING_CIRCUMFERENCE}`}
                className="transition-all duration-500"
              />
            </svg>
          ) : (
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
              {stat.icon}
            </span>
          )}
          <div className="min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-semibold leading-none tabular-nums">
                {stat.value}
              </span>
              <span className="truncate text-xs font-medium text-muted-foreground">
                {stat.label}
              </span>
            </div>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {stat.detail}
            </p>
          </div>
        </div>
      );
    })}
  </div>
);

const ProjectSkeleton = () => (
  <div className="flex flex-col">
    {Array.from({ length: 5 }).map((_, index) => (
      <div key={index} className="flex items-start gap-3 border-b p-4">
        <Skeleton className="size-9 rounded-md" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-3/4" />
          <Skeleton className="h-7 w-52" />
        </div>
      </div>
    ))}
  </div>
);

const ProjectStatusBadge = ({
  active,
  short = false,
}: {
  active: boolean;
  short?: boolean;
}) => (
  <Badge
    variant="outline"
    className={cn(
      "border-border bg-muted/40 text-muted-foreground",
      active && "border-emerald-200 bg-emerald-50 text-emerald-700",
    )}
  >
    {active ? (short ? "Đang bật" : "Đang hoạt động") : "Tắt"}
  </Badge>
);

const ProjectManagementRow = ({
  project,
  selected,
  onSelect,
  isAdmin,
}: {
  project: Project;
  selected: boolean;
  onSelect: () => void;
  isAdmin: boolean;
}) => {
  const notify = useNotify();
  const refresh = useRefresh();

  const onReindex = async () => {
    try {
      await reindexProject(String(project.id));
      notify("Đã làm mới thẻ danh mục dự án.", { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect();
      }}
      className={cn(
        "group border-b px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted focus-visible:outline-none",
        selected && "bg-muted/70",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <Boxes className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">
                {project.name}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <span className="font-mono">{project.slug}</span>
                <span>•</span>
                <MapPin className="size-3" />
                <span className="truncate">{getProjectLocation(project)}</span>
              </div>
            </div>
            <div
              className="flex shrink-0 items-center gap-1"
              onClick={(event) => event.stopPropagation()}
            >
              <ProjectStatusBadge active={project.is_active} short />
              {isAdmin && (
                <ProjectActionsMenu
                  project={project}
                  onReindex={onReindex}
                  onDeleted={() => refresh()}
                />
              )}
            </div>
          </div>
          {project.summary && (
            <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
              {project.summary}
            </p>
          )}
          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <ReadinessRing
              ready={project.feature_readiness?.ready}
              total={project.feature_readiness?.total ?? 16}
              size="size-7"
            />
            <span className="truncate tabular-nums">
              {typeof project.feature_readiness?.ready === "number"
                ? `${project.feature_readiness.ready}/${project.feature_readiness?.total ?? 16} có thể tư vấn`
                : "—"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

const ProjectActionsMenu = ({
  project,
  onReindex,
  onDeleted,
}: {
  project: Project;
  onReindex: () => void;
  onDeleted: () => void;
}) => {
  const redirect = useRedirect();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 opacity-70 transition-opacity group-hover:opacity-100"
          aria-label={`Mở thao tác cho ${project.name}`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuItem
          onSelect={() => redirect("edit", "projects", project.id)}
        >
          <Pencil className="size-4" />
          Sửa
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onReindex}>
          <RefreshCw className="size-4" />
          Làm mới thẻ
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DeleteButton
          record={project}
          resource="projects"
          label="Xóa"
          size="sm"
          variant="ghost"
          redirect={false}
          successMessage="Đã xóa dự án."
          mutationOptions={{ onSuccess: onDeleted }}
          className="h-8 w-full justify-start px-2 text-sm text-destructive hover:bg-destructive/10"
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

const ProjectDetailPanel = ({
  project,
  docs,
  isAdmin,
  onUpload,
}: {
  project: Project;
  docs: KnowledgeSource[];
  isAdmin: boolean;
  onUpload: () => void;
}) => {
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();
  const highlights = getProjectHighlights(project);
  const card = project.index_card ?? {};

  const retrySource = async (source: KnowledgeSource) => {
    try {
      await reindexKnowledge(String(source.id));
      notify("Đã đưa tài liệu vào hàng xử lý lại.", { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thử lại thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <div className="space-y-4">
      {/* key on project.id so the whole panel (incl. disclosure + FeatureCard
          local draft state) resets when the recruiter selects another project.
          Rendered FIRST so readiness is the unmistakable hero of the detail. */}
      <ProjectFeatures
        key={String(project.id)}
        projectId={String(project.id)}
        editable={isAdmin}
      />

      <details className="group rounded-lg border bg-card text-card-foreground shadow-sm">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 border-b px-4 py-3 text-sm font-semibold transition-colors group-open:[&>svg]:rotate-180 hover:bg-muted/50">
          <span>Thông tin thêm</span>
          <ChevronDown className="size-4 text-muted-foreground transition-transform" />
        </summary>
        <div className="space-y-4 px-4 py-4">
          <Card className="border-0 shadow-none">
            <CardHeader className="gap-3 border-b px-0">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle className="truncate text-lg">
                    {project.name}
                  </CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {project.slug} • {getProjectLocation(project)}
                  </p>
                </div>
                <ProjectStatusBadge active={project.is_active} />
              </div>
              {isAdmin && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => redirect("edit", "projects", project.id)}
                  >
                    <Pencil className="size-4" />
                    Cập nhật
                  </Button>
                  <Button variant="outline" size="sm" onClick={onUpload}>
                    <Upload className="size-4" />
                    Thêm kiến thức
                  </Button>
                </div>
              )}
            </CardHeader>
            <CardContent className="space-y-4 px-0 pt-4">
              <section>
                <h3 className="text-sm font-semibold">Product card</h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {project.summary ??
                    "Chưa có tóm tắt. Tải tin tuyển dụng rồi làm mới thẻ danh mục."}
                </p>
              </section>
              <div className="grid gap-3 md:grid-cols-2">
                <InfoBlock
                  label="Vị trí tuyển"
                  value={(card.key_roles ?? []).join(", ") || "Chưa có"}
                />
                <InfoBlock
                  label="Nguồn kiến thức"
                  value={`${docs.length} tài liệu`}
                />
              </div>
              <section>
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">Điểm nổi bật</h3>
                  <span className="text-xs text-muted-foreground">
                    {highlights.length} mục
                  </span>
                </div>
                {highlights.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {highlights.map((highlight) => (
                      <Badge key={highlight} variant="secondary">
                        {highlight}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-sm text-muted-foreground">
                    Chưa có điểm nổi bật để agent ưu tiên khi tư vấn.
                  </p>
                )}
              </section>
              <section>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">Tài liệu liên kết</h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => redirect("/knowledge_sources")}
                  >
                    Xem kho kiến thức
                  </Button>
                </div>
                {docs.length > 0 ? (
                  <div className="space-y-2">
                    {docs.slice(0, 4).map((doc) => (
                      <div
                        key={doc.id}
                        className="flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-muted/50"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            redirect("show", "knowledge_sources", doc.id)
                          }
                          className="min-w-0 flex-1 truncate text-left"
                        >
                          {doc.file_name}
                        </button>
                        <span
                          className={cn(
                            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                            stageTone(doc.stage, doc.status),
                          )}
                        >
                          {stageLabel(doc.stage ?? doc.status)}
                        </span>
                        {isFailedSource(doc) && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="size-7 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                            onClick={() => retrySource(doc)}
                            title="Thử xử lý lại tài liệu"
                          >
                            <RefreshCw className="size-3.5" />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                    Chưa có tài liệu nào gắn với dự án này.
                  </div>
                )}
              </section>
            </CardContent>
          </Card>
        </div>
      </details>
    </div>
  );
};

const InfoBlock = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-md bg-muted/40 p-3">
    <div className="text-xs uppercase tracking-wide text-muted-foreground">
      {label}
    </div>
    <div className="mt-1 text-sm font-medium">{value}</div>
  </div>
);

export const ProjectList = () => (
  <ListBase perPage={100} sort={{ field: "name", order: "ASC" }}>
    <ProjectListContent />
  </ListBase>
);
