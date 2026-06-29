import { useEffect, useMemo, useState } from "react";
import {
  ListBase,
  useListContext,
  useNotify,
  usePermissions,
  useRedirect,
  useRefresh,
} from "ra-core";
import {
  Activity,
  Boxes,
  BusFront,
  ChevronLeft,
  ChevronRight,
  FileText,
  HelpCircle,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Star,
  Upload,
} from "lucide-react";
import { DeleteButton } from "@/components/admin";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { TopToolbar } from "../layout/TopToolbar";
import type { BusRoute, BusTimetableList, Project } from "../types";
import {
  getProjectFaq,
  getProjectBusTimetable,
  type ProjectFaqList,
  reindexProject,
} from "@/lib/vfic/knowledgeService";
import { KnowledgeUpload } from "../knowledge/KnowledgeUpload";
import { ProjectFeatures } from "./ProjectFeatures";

const ProjectListContent = () => {
  const { data, isPending } = useListContext<Project>();
  const { permissions } = usePermissions();
  const isAdmin = permissions === "admin";
  const canEdit = permissions === "admin" || permissions === "recruiter";
  const refresh = useRefresh();
  const redirect = useRedirect();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  const projects = useMemo(() => data ?? [], [data]);

  useEffect(() => {
    if (projects.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !projects.some((project) => project.id === selectedId)) {
      setSelectedId(String(projects[0].id));
    }
  }, [projects, selectedId]);

  const selectedProject =
    projects.find((project) => project.id === selectedId) ?? projects[0] ??
    null;
  const activeCount = projects.filter((project) => project.is_active).length;
  const totalDocs = projects.reduce(
    (sum, project) => sum + (project.knowledge_document_count ?? 0),
    0,
  );
  const projectWithDocs = projects.filter(
    (project) => (project.knowledge_document_count ?? 0) > 0,
  ).length;

  return (
    <div className="min-h-[calc(100vh-7rem)] px-4 py-5 pb-24 md:px-0 md:py-0 md:pb-0">
      <TopToolbar className="flex-wrap items-start gap-3">
        <div className="mr-auto min-w-0">
          <h2 className="text-2xl font-bold tracking-tight md:text-3xl">
            Quản lý dự án
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Theo dõi thẻ sản phẩm, nguồn kiến thức và các đặc điểm sản phẩm mà
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
            label: "Thẻ sản phẩm",
            value: String(projects.filter((project) => project.summary).length),
            detail: "Có tóm tắt / thẻ danh mục",
          },
        ]}
      />

      <div className="mt-4 space-y-4">
        <ProjectSwitcher
          projects={projects}
          selectedProject={selectedProject}
          selectedId={selectedId}
          isPending={isPending}
          isAdmin={isAdmin}
          canEdit={canEdit}
          onSelect={setSelectedId}
        />
        {selectedProject ? (
          <ProjectDetailPanel
            project={selectedProject}
            isAdmin={isAdmin}
            canEdit={canEdit}
          />
        ) : (
          <EmptyState
            icon={<Boxes className="size-6" />}
            title="Chưa có dự án"
            description="Tạo dự án mới hoặc tải kiến thức để agent có ngữ cảnh tư vấn."
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

const ProjectSwitcher = ({
  projects,
  selectedProject,
  selectedId,
  isPending,
  isAdmin,
  canEdit,
  onSelect,
}: {
  projects: Project[];
  selectedProject: Project | null;
  selectedId: string | null;
  isPending: boolean;
  isAdmin: boolean;
  canEdit: boolean;
  onSelect: (id: string) => void;
}) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const redirect = useRedirect();

  const onReindex = async () => {
    if (!selectedProject) return;
    try {
      await reindexProject(String(selectedProject.id));
      notify("Đã làm mới thẻ danh mục dự án.", { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-2 text-sm font-semibold">Dự án đang xem</div>
          {isPending ? (
            <Skeleton className="h-10 w-full max-w-md" />
          ) : projects.length > 0 ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <Select
                value={selectedId ?? undefined}
                onValueChange={(value) => onSelect(value)}
              >
                <SelectTrigger className="h-10 w-full sm:max-w-md">
                  <SelectValue placeholder="Chọn dự án" />
                </SelectTrigger>
                <SelectContent className="max-h-80">
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={String(project.id)}>
                      <span className="block truncate">
                        {project.name} · {project.slug}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedProject && (
                <div className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
                  <ProjectStatusBadge active={selectedProject.is_active} short />
                  <ReadinessRing
                    ready={selectedProject.feature_readiness?.ready}
                    total={selectedProject.feature_readiness?.total ?? 16}
                    size="size-7"
                  />
                  <span className="truncate tabular-nums">
                    {typeof selectedProject.feature_readiness?.ready ===
                    "number"
                      ? `${selectedProject.feature_readiness.ready}/${selectedProject.feature_readiness?.total ?? 16} có thể tư vấn`
                      : "Chưa có dữ liệu tư vấn"}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Chưa có dự án nào để chọn.
            </p>
          )}
        </div>
        {selectedProject && (
          <div className="flex shrink-0 items-center gap-2">
            {canEdit && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => redirect("edit", "projects", selectedProject.id)}
              >
                <Pencil className="size-4" />
                Sửa thông tin
              </Button>
            )}
            {isAdmin && (
              <ProjectActionsMenu
                project={selectedProject}
                onReindex={onReindex}
                onDeleted={() => refresh()}
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
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
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 opacity-80 transition-opacity hover:opacity-100"
          aria-label={`Mở thao tác cho ${project.name}`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
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
  isAdmin,
  canEdit,
}: {
  project: Project;
  isAdmin: boolean;
  canEdit: boolean;
}) => {
  return (
    <ProjectFeatures
      key={String(project.id)}
      projectId={String(project.id)}
      editable={canEdit}
      canExtract={isAdmin}
      extraContent={
        <div className="space-y-5">
          <ProjectFaqSection projectId={String(project.id)} />
          <BusTimetableSection projectId={String(project.id)} />
        </div>
      }
    />
  );
};

const shiftLabel = (shift: string) =>
  (
    {
      admin: "Hành chính",
      day: "Ca ngày",
      night: "Ca đêm",
    } as Record<string, string>
  )[shift] ?? shift;

const directionLabel = (direction: string) =>
  (
    {
      outbound: "Lượt đi",
      return: "Lượt về",
    } as Record<string, string>
  )[direction] ?? direction;

const BUS_ROUTE_PAGE_SIZE = 6;

const ProjectFaqSection = ({ projectId }: { projectId: string }) => {
  const [faq, setFaq] = useState<ProjectFaqList | null>(null);
  const [loading, setLoading] = useState(true);
  const items = faq?.data ?? [];

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectFaq(projectId)
      .then((res) => {
        if (!cancelled) setFaq(res);
      })
      .catch(() => {
        if (!cancelled) setFaq({ data: [], total: 0 });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="inline-flex items-center gap-2 text-base font-semibold">
          <HelpCircle className="size-4 text-muted-foreground" />
          FAQ
        </h3>
        <span className="text-sm text-muted-foreground">
          {loading && !faq ? "Đang tải..." : `${faq?.total ?? 0} câu`}
        </span>
      </div>
      {loading && !faq ? (
        <div className="mt-3 grid gap-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : items.length > 0 ? (
        <div className="mt-3 grid gap-3">
          {items.map((item) => (
            <article key={item.id} className="rounded-md border bg-muted/15 p-3">
              <h4 className="text-sm font-semibold leading-5">{item.question}</h4>
              <p className="mt-2 whitespace-pre-line text-sm leading-6 text-muted-foreground">
                {item.answer}
              </p>
              {(item.source_name || item.source_anchor) && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Nguồn: {item.source_name || item.source_anchor}
                </p>
              )}
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
          Chưa có FAQ được trích xuất cho dự án này.
        </p>
      )}
    </section>
  );
};

const BusTimetableSection = ({ projectId }: { projectId: string }) => {
  const [page, setPage] = useState(1);
  const [timetable, setTimetable] = useState<BusTimetableList | null>(null);
  const [loading, setLoading] = useState(true);
  const routes = timetable?.data ?? [];
  const total = timetable?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / BUS_ROUTE_PAGE_SIZE));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectBusTimetable(projectId, {
      page,
      perPage: BUS_ROUTE_PAGE_SIZE,
    })
      .then((res) => {
        if (!cancelled) setTimetable(res);
      })
      .catch(() => {
        if (!cancelled) {
          setTimetable({
            data: [],
            total: 0,
            page,
            per_page: BUS_ROUTE_PAGE_SIZE,
          });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, page]);

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="inline-flex items-center gap-2 text-base font-semibold">
          <BusFront className="size-4 text-muted-foreground" />
          Lịch xe đưa đón
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">
            {loading && !timetable ? "Đang tải..." : `${total} tuyến`}
          </span>
          {total > BUS_ROUTE_PAGE_SIZE && (
            <span className="text-xs text-muted-foreground">
              Trang {page}/{pageCount}
            </span>
          )}
          {total > BUS_ROUTE_PAGE_SIZE && (
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8"
                disabled={loading || page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                aria-label="Trang trước"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8"
                disabled={loading || page >= pageCount}
                onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
                aria-label="Trang sau"
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          )}
        </div>
      </div>
      {loading && !timetable ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : routes.length > 0 ? (
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          {routes.map((route) => (
            <BusRouteCard key={route.id} route={route} />
          ))}
        </div>
      ) : (
        <p className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
          Chưa có lịch xe đưa đón được trích xuất cho dự án này.
        </p>
      )}
    </section>
  );
};

const BusRouteCard = ({ route }: { route: BusRoute }) => (
  <div className="rounded-md border bg-muted/15 p-3">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-semibold leading-5">{route.route_name}</h4>
          {route.route_no && (
            <Badge variant="outline" className="h-5 rounded-md px-1.5 text-[10px]">
              Tuyến {route.route_no}
            </Badge>
          )}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {shiftLabel(route.shift)} • {directionLabel(route.direction)}
        </div>
      </div>
      <Badge variant="secondary" className="shrink-0 text-[10px]">
        {route.stops.length} điểm
      </Badge>
    </div>

    {route.stops.length > 0 ? (
      <div className="mt-3 flex flex-wrap gap-1.5">
        {route.stops.map((stop) => (
          <span
            key={stop.id}
            className="inline-flex max-w-full items-center gap-1 rounded-md border bg-card px-2 py-1 text-xs"
          >
            <span className="max-w-[180px] truncate font-medium">
              {stop.stop_name}
            </span>
            {stop.scheduled_time && (
              <span className="font-mono text-[11px] text-muted-foreground">
                {stop.scheduled_time}
              </span>
            )}
          </span>
        ))}
      </div>
    ) : (
      <p className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        Chưa có điểm đón cho tuyến này.
      </p>
    )}
  </div>
);

export const ProjectList = () => (
  <ListBase perPage={100} sort={{ field: "name", order: "ASC" }}>
    <ProjectListContent />
  </ListBase>
);
