import { memo, useEffect, useMemo, useState } from "react";
import {
  ListBase,
  useListContext,
  useNotify,
  useRedirect,
  useRefresh,
} from "ra-core";
import { useMasterDetailSelection } from "../hooks/useMasterDetailSelection";
import {
  Boxes,
  BusFront,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  FileText,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Upload,
} from "lucide-react";
import { DeleteButton } from "@/components/admin";
import { ListPagination } from "@/components/admin/list-pagination";
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
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { BusRoute, BusTimetableList, Project } from "../types";
import {
  getProjectBusTimetable,
  reindexProject,
} from "@/lib/vfic/knowledgeService";
import { KnowledgeUpload } from "../knowledge/KnowledgeUpload";
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectFeatures } from "./ProjectFeatures";
import { ProjectFaqEditor } from "./ProjectFaqEditor";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

const ProjectListContent = () => {
  const { data, isPending, total } = useListContext<Project>();
  const { isAdmin, canEdit } = useRoleActions();
  const refresh = useRefresh();
  const redirect = useRedirect();
  const notify = useNotify();
  const [uploadOpen, setUploadOpen] = useState(false);

  const projects = useMemo(() => data ?? [], [data]);
  const activeCount = useMemo(
    () => projects.filter((project) => project.is_active).length,
    [projects],
  );
  const documentCount = useMemo(
    () =>
      projects.reduce(
        (sum, project) => sum + (project.knowledge_document_count ?? 0),
        0,
      ),
    [projects],
  );
  const readiness = useMemo(
    () =>
      projects.reduce(
        (acc, project) => {
          const totalFeatures = project.feature_readiness?.total ?? 0;
          const readyFeatures = project.feature_readiness?.ready ?? 0;
          return {
            ready: acc.ready + readyFeatures,
            total: acc.total + totalFeatures,
          };
        },
        { ready: 0, total: 0 },
      ),
    [projects],
  );

  const { selectedId, setSelectedId } = useMasterDetailSelection<Project>({
    data: projects,
  });

  const selectedProject =
    projects.find((project) => project.id === selectedId) ??
    projects[0] ??
    null;

  const onReindex = async (project: Project) => {
    try {
      await reindexProject(String(project.id));
      notify("Đã làm mới thẻ danh mục dự án.", { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <ProjectWorkspaceShell
      total={total ?? projects.length}
      activeCount={activeCount}
      documentCount={documentCount}
    >
      <div className="project-workspace-content">
        <div className="ops-page-shell project-page-shell">
          <header className="ops-command-header project-command-header">
            <div className="ops-command-title">
              <div className="ops-command-mark">
                <Boxes className="size-5" />
              </div>
              <div className="min-w-0">
                <p className="ops-kicker">Không gian dự án</p>
                <h1>Dự án tuyển dụng</h1>
                <p>
                  Theo dõi thẻ sản phẩm, nguồn kiến thức và các đặc điểm mà
                  chatbot dùng khi tư vấn ứng viên.
                </p>
              </div>
            </div>
            <div className="project-command-actions">
              <Button
                variant="outline"
                onClick={() => refresh()}
                className="h-11 rounded-[9px]"
              >
                <RefreshCw className="size-4" />
                Làm mới
              </Button>
              {isAdmin && (
                <>
                  <Button
                    variant="outline"
                    onClick={() => setUploadOpen(true)}
                    className="h-11 rounded-[9px]"
                  >
                    <Upload className="size-4" />
                    Tải kiến thức
                  </Button>
                  <Button
                    onClick={() => redirect("create", "projects")}
                    className="h-11 rounded-[9px]"
                  >
                    <Plus className="size-4" />
                    Tạo dự án
                  </Button>
                </>
              )}
            </div>
          </header>

          <section className="ops-status-strip project-status-strip">
            <div>
              <span className="ops-status-label">Tổng dự án</span>
              <strong>{total ?? projects.length}</strong>
            </div>
            <div>
              <span className="ops-status-label">Đang bật</span>
              <strong>{activeCount}</strong>
            </div>
            <div>
              <span className="ops-status-label">Tài liệu training</span>
              <strong>{documentCount}</strong>
            </div>
            <div>
              <span className="ops-status-label">Sẵn sàng tư vấn</span>
              <strong>
                {readiness.total > 0
                  ? `${readiness.ready}/${readiness.total}`
                  : "—"}
              </strong>
            </div>
          </section>

          <div className="project-layout-grid">
            <ProjectDirectoryPanel
              projects={projects}
              selectedId={selectedId}
              isPending={isPending}
              onSelect={setSelectedId}
            />
            <ProjectSpotlightPanel
              project={selectedProject}
              isAdmin={isAdmin}
              canEdit={canEdit}
              onEdit={() =>
                selectedProject &&
                redirect("edit", "projects", selectedProject.id)
              }
              onReindex={() => selectedProject && onReindex(selectedProject)}
              onDeleted={() => refresh()}
            />
          </div>

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

          <ListPagination
            rowsPerPageOptions={[10, 25, 50, 100]}
            className="ops-pagination"
          />
        </div>

        {isAdmin && (
          <KnowledgeUpload open={uploadOpen} onOpenChange={setUploadOpen} />
        )}
      </div>
    </ProjectWorkspaceShell>
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
        stroke="var(--feature-ready)"
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

const ProjectDirectoryPanel = ({
  projects,
  selectedId,
  isPending,
  onSelect,
}: {
  projects: Project[];
  selectedId: string | null;
  isPending: boolean;
  onSelect: (id: string) => void;
}) => {
  return (
    <section className="ops-panel project-directory-panel">
      <div className="ops-panel-header">
        <div className="ops-panel-title">
          <p className="ops-panel-eyebrow">Danh mục dự án</p>
          <h2>Dự án đang quản lý</h2>
        </div>
        <Badge variant="outline" className="border-border bg-background/70">
          {projects.length} mục
        </Badge>
      </div>
      <div className="project-directory-list">
        {isPending ? (
          <div className="project-directory-loading">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="project-directory-skeleton">
                <Skeleton className="size-10 rounded-[10px]" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-44" />
                  <Skeleton className="h-3 w-64 max-w-full" />
                </div>
              </div>
            ))}
          </div>
        ) : projects.length > 0 ? (
          projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className={cn(
                "project-directory-row",
                String(project.id) === selectedId && "is-active",
              )}
              onClick={() => onSelect(String(project.id))}
              aria-pressed={String(project.id) === selectedId}
            >
              <div className="project-directory-avatar">
                <Boxes className="size-4" />
              </div>
              <div className="project-directory-copy">
                <div className="project-directory-title-line">
                  <div className="min-w-0">
                    <span className="project-directory-name">
                      {project.name}
                    </span>
                    <span className="project-directory-slug">
                      {project.slug}
                    </span>
                  </div>
                  <ProjectStatusBadge active={project.is_active} short />
                </div>
                <div className="project-directory-meta">
                  <span>
                    <FileText className="size-3.5" />
                    {project.knowledge_document_count ?? 0} tài liệu
                  </span>
                  <span>
                    <CheckCircle2 className="size-3.5" />
                    {typeof project.feature_readiness?.ready === "number"
                      ? `${project.feature_readiness.ready}/${project.feature_readiness?.total ?? 16}`
                      : "Chưa đo"}
                  </span>
                </div>
              </div>
            </button>
          ))
        ) : (
          <EmptyState
            icon={<Boxes className="size-6" />}
            title="Chưa có dự án"
            description="Tạo dự án mới để gom kiến thức và đặc điểm tư vấn."
            className="project-empty-state"
          />
        )}
      </div>
    </section>
  );
};

const ProjectSpotlightPanel = ({
  project,
  isAdmin,
  canEdit,
  onEdit,
  onReindex,
  onDeleted,
}: {
  project: Project | null;
  isAdmin: boolean;
  canEdit: boolean;
  onEdit: () => void;
  onReindex: () => void;
  onDeleted: () => void;
}) => {
  if (!project) {
    return (
      <aside className="project-spotlight-panel">
        <EmptyState
          icon={<Boxes className="size-6" />}
          title="Chọn dự án"
          description="Thông tin vận hành của dự án sẽ hiện tại đây."
          className="project-spotlight-empty"
        />
      </aside>
    );
  }

  const readinessReady = project.feature_readiness?.ready;
  const readinessTotal = project.feature_readiness?.total ?? 16;

  return (
    <aside className="project-spotlight-panel">
      <div className="project-spotlight-top">
        <ReadinessRing
          ready={readinessReady}
          total={readinessTotal}
          size="size-12"
        />
        <div className="min-w-0">
          <div className="project-spotlight-badges">
            <ProjectStatusBadge active={project.is_active} />
            <Badge variant="outline" className="border-border bg-muted/35">
              {project.default_persona_id ? "Có agent" : "Chưa gắn agent"}
            </Badge>
          </div>
          <h2>{project.name}</h2>
          <p>{project.slug}</p>
        </div>
      </div>

      <div className="project-spotlight-metrics">
        <div>
          <span>Tài liệu</span>
          <strong>{project.knowledge_document_count ?? 0}</strong>
        </div>
        <div>
          <span>Sẵn sàng</span>
          <strong>
            {typeof readinessReady === "number"
              ? `${readinessReady}/${readinessTotal}`
              : "—"}
          </strong>
        </div>
      </div>

      {project.summary || project.index_card?.summary ? (
        <div className="project-summary-panel">
          <span>Tóm tắt</span>
          <p>{project.index_card?.summary ?? project.summary}</p>
        </div>
      ) : null}

      <div className="project-spotlight-actions">
        {canEdit && (
          <Button variant="outline" size="sm" onClick={onEdit} className="h-11">
            <Pencil className="size-4" />
            Sửa thông tin
          </Button>
        )}
        {isAdmin && (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={onReindex}
              className="h-11"
            >
              <RefreshCw className="size-4" />
              Làm mới thẻ
            </Button>
            <ProjectActionsMenu
              project={project}
              onReindex={onReindex}
              onDeleted={onDeleted}
            />
          </>
        )}
      </div>
    </aside>
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
          className="size-11 opacity-80 transition-opacity hover:opacity-100"
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
    <div className="project-detail-stack">
      <ProjectFeatures
        key={String(project.id)}
        projectId={String(project.id)}
        editable={canEdit}
        canExtract={isAdmin}
        extraContent={
          <div className="space-y-5">
            <ProjectFaqEditor
              projectId={String(project.id)}
              editable={canEdit}
              embedded
            />
            <BusTimetableSection projectId={String(project.id)} />
          </div>
        }
      />
    </div>
  );
};

const shiftLabel = (shift: string) =>
  (
    ({
      admin: "Hành chính",
      day: "Ca ngày",
      night: "Ca đêm",
    }) as Record<string, string>
  )[shift] ?? shift;

const directionLabel = (direction: string) =>
  (
    ({
      outbound: "Lượt đi",
      return: "Lượt về",
    }) as Record<string, string>
  )[direction] ?? direction;

const BUS_ROUTE_PAGE_SIZE = 6;

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
                onClick={() =>
                  setPage((value) => Math.min(pageCount, value + 1))
                }
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
        <p
          role="status"
          className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-sm text-muted-foreground"
        >
          Chưa có lịch xe đưa đón được trích xuất cho dự án này.
        </p>
      )}
    </section>
  );
};

const BusRouteCard = memo(({ route }: { route: BusRoute }) => (
  <div className="rounded-md border bg-muted/15 p-3">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-semibold leading-5">
            {route.route_name}
          </h4>
          {route.route_no && (
            <Badge
              variant="outline"
              className="h-5 rounded-md px-1.5 text-[10px]"
            >
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
      <p
        role="status"
        className="mt-3 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-xs text-muted-foreground"
      >
        Chưa có điểm đón cho tuyến này.
      </p>
    )}
  </div>
));
BusRouteCard.displayName = "BusRouteCard";

export const ProjectList = () => (
  <ListBase perPage={25} sort={{ field: "name", order: "ASC" }}>
    <ProjectListContent />
  </ListBase>
);
