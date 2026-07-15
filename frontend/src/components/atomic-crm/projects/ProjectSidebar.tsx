import {
  Bot,
  Boxes,
  CheckCircle2,
  FileText,
  MoreHorizontal,
  Pencil,
} from "lucide-react";
import { DeleteButton } from "@/components/admin";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Project } from "../types";

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

const ProjectActionsMenu = ({
  project,
  onDeleted,
}: {
  project: Project;
  onDeleted: () => void;
}) => {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-11 opacity-80 transition-opacity hover:opacity-100 md:size-9"
          aria-label={`Mở thao tác cho ${project.name}`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DeleteButton
          record={project}
          resource="projects"
          label="Xóa"
          size="sm"
          variant="ghost"
          redirect={false}
          successMessage="Đã xóa dự án."
          mutationOptions={{ onSuccess: onDeleted }}
          className="h-8 w-full justify-start px-2 text-button text-destructive hover:bg-destructive/10"
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

const SelectedProjectSummary = ({
  project,
  isAdmin,
  canEdit,
  onEdit,
  onDeleted,
}: {
  project: Project | null;
  isAdmin: boolean;
  canEdit: boolean;
  onEdit: () => void;
  onDeleted: () => void;
}) => {
  if (!project) {
    return (
      <aside className="project-selected-summary">
        <EmptyState
          icon={<Boxes className="size-6" />}
          title="Chọn dự án"
          description="Chọn một dự án để xem readiness, tài liệu và thiết lập agent."
          className="project-spotlight-empty"
        />
      </aside>
    );
  }

  const readinessReady = project.feature_readiness?.ready;
  const readinessTotal = project.feature_readiness?.total ?? 16;
  const readinessText =
    typeof readinessReady === "number"
      ? `${readinessReady}/${readinessTotal}`
      : "Chưa đo";

  return (
    <aside className="project-selected-summary">
      <div className="project-selected-main">
        <div className="min-w-0">
          <div className="project-selected-eyebrow">Tổng quan dự án</div>
          <h2>{project.name}</h2>
          <div className="project-selected-slug">{project.slug}</div>
        </div>
        <div className="project-selected-actions">
          {canEdit && (
            <Button
              variant="outline"
              size="sm"
              onClick={onEdit}
              className="project-edit-action h-11 md:h-9"
              aria-label={`Chỉnh sửa ${project.name}`}
            >
              <Pencil className="size-4" />
              <span>Sửa</span>
            </Button>
          )}
          {isAdmin && (
            <ProjectActionsMenu project={project} onDeleted={onDeleted} />
          )}
        </div>
      </div>

      <div className="project-health-row" aria-label="Tình trạng dự án">
        <ProjectStatusBadge active={project.is_active} />
      </div>

      <dl className="project-fact-row" aria-label="Tóm tắt dự án">
        <div>
          <dt>
            <FileText className="size-3.5" />
            Tài liệu
          </dt>
          <dd>{project.knowledge_document_count ?? 0}</dd>
        </div>
        <div>
          <dt>
            <CheckCircle2 className="size-3.5" />
            Thông tin đủ
          </dt>
          <dd>{readinessText}</dd>
        </div>
        <div>
          <dt>
            <Bot className="size-3.5" />
            Agent
          </dt>
          <dd>{project.default_persona_id ? "Đã chọn" : "Chưa chọn"}</dd>
        </div>
      </dl>

      {(project.summary || project.index_card?.summary) && (
        <p className="project-selected-summary-text">
          {project.index_card?.summary ?? project.summary}
        </p>
      )}
    </aside>
  );
};

export const ProjectOperationsPanel = ({
  projects,
  selectedId,
  selectedProject,
  isPending,
  isAdmin,
  canEdit,
  onSelect,
  onEdit,
  onDeleted,
}: {
  projects: Project[];
  selectedId: string | null;
  selectedProject: Project | null;
  isPending: boolean;
  isAdmin: boolean;
  canEdit: boolean;
  onSelect: (id: string) => void;
  onEdit: () => void;
  onDeleted: () => void;
}) => {
  const hasProjectChoice = projects.length > 1;

  return (
    <section
      className={cn(
        "project-ops-panel",
        !hasProjectChoice && !isPending && "is-single-project",
      )}
    >
      {(hasProjectChoice || isPending || projects.length === 0) && (
        <div className="project-selector-column">
          <div className="project-section-heading">
            <span>Danh mục dự án</span>
            <strong>{projects.length} mục</strong>
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
        </div>
      )}

      {selectedProject && (
        <SelectedProjectSummary
          project={selectedProject}
          isAdmin={isAdmin}
          canEdit={canEdit}
          onEdit={onEdit}
          onDeleted={onDeleted}
        />
      )}
    </section>
  );
};
