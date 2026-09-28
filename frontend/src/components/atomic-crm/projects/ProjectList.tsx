import { useMemo } from "react";
import {
  ListBase,
  useListContext,
  useNotify,
  useRedirect,
  useRefresh,
  useUpdate,
} from "ra-core";
import {
  Boxes,
  CheckCircle2,
  FileText,
  Pencil,
  Plus,
  Power,
  PowerOff,
} from "lucide-react";
import { ListPagination } from "@/components/admin/list-pagination";
import { DeleteButton } from "@/components/admin";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "../kit";
import { cn } from "@/lib/utils";
import type { Project } from "../types";
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectKnowledgePanel } from "./ProjectKnowledgePanel";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";
import {
  aggregateProjectFeatureReadiness,
  projectReadinessLabel,
} from "./domain/project-knowledge-policy";

const ProjectListContent = () => {
  const { data, isPending, total } = useListContext<Project>();
  const { isAdmin, canEdit } = useRoleActions();
  const refresh = useRefresh();
  const redirect = useRedirect();
  const notify = useNotify();
  const [updateProject, { isPending: isTogglingActive }] = useUpdate();

  // Turning a project off keeps its documents and mappings intact; it only
  // drops out of the catalog the bot answers from, which is why this is a
  // toggle rather than a delete.
  const toggleActive = (project: Project) => {
    const nextActive = !project.is_active;
    updateProject(
      "projects",
      {
        id: project.id,
        data: { is_active: nextActive },
        previousData: project,
      },
      {
        onSuccess: () => {
          notify(nextActive ? "Đã bật dự án." : "Đã tắt dự án.", {
            type: "success",
          });
          refresh();
        },
        onError: () => {
          notify(nextActive ? "Không thể bật dự án." : "Không thể tắt dự án.", {
            type: "error",
          });
        },
      },
    );
  };

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
    () => aggregateProjectFeatureReadiness(projects),
    [projects],
  );

  const projectTotal = total ?? projects.length;

  return (
    <ProjectWorkspaceShell>
      <div className="project-workspace-content">
        <div className="ops-page-shell project-page-shell">
          <header className="ops-command-header project-command-header">
            <div className="ops-command-title">
              <div className="min-w-0">
                <h1>Dự án tuyển dụng</h1>
                <p>Theo dõi trạng thái, tài liệu và độ sẵn sàng kiến thức.</p>
              </div>
            </div>
            <div className="project-command-actions">
              {isAdmin && (
                <Button
                  size="sm"
                  onClick={() => redirect("create", "projects")}
                  className="project-create-button"
                >
                  <Plus className="size-4" />
                  Tạo dự án
                </Button>
              )}
            </div>
          </header>

          {projects.length > 0 && (
            <section
              className="project-rollup-strip"
              aria-label="Tóm tắt dự án"
            >
              <span>{projectTotal} dự án</span>
              <span>{activeCount} đang bật</span>
              <span>{documentCount} tài liệu</span>
              <span>
                {readiness.total > 0
                  ? `${readiness.ready}/${readiness.total} sẵn sàng`
                  : "Chưa đo readiness"}
              </span>
            </section>
          )}

          {isPending ? (
            <ProjectAccordionSkeleton />
          ) : projects.length > 0 ? (
            <ProjectAccordionList
              projects={projects}
              isAdmin={isAdmin}
              canEdit={canEdit}
              onEdit={(project) => redirect("edit", "projects", project.id)}
              onDeleted={() => refresh()}
              onToggleActive={toggleActive}
              isTogglingActive={isTogglingActive}
            />
          ) : (
            <EmptyState
              icon={<Boxes className="size-6" />}
              title="Chưa có dự án"
              description="Tạo dự án mới hoặc tải kiến thức để agent có ngữ cảnh tư vấn."
              className="min-h-[420px]"
            />
          )}

          {projectTotal > 25 && (
            <ListPagination
              rowsPerPageOptions={[10, 25, 50, 100]}
              className="ops-pagination"
            />
          )}
        </div>
      </div>
    </ProjectWorkspaceShell>
  );
};

export const ProjectAccordionList = ({
  projects,
  isAdmin,
  canEdit,
  onEdit,
  onDeleted,
  onToggleActive,
  isTogglingActive = false,
}: {
  projects: Project[];
  isAdmin: boolean;
  canEdit: boolean;
  onEdit: (project: Project) => void;
  onDeleted: () => void;
  // Optional so callers that only render the list (tests, embeds) need not
  // wire a mutation to show projects.
  onToggleActive?: (project: Project) => void;
  isTogglingActive?: boolean;
}) => {
  return (
    <Accordion type="single" collapsible className="project-accordion-list">
      {projects.map((project) => {
        const projectId = String(project.id);
        const readinessText = projectReadinessLabel(project);

        return (
          <AccordionItem
            key={projectId}
            value={projectId}
            className="project-accordion-item"
          >
            <AccordionTrigger
              className="project-accordion-trigger"
              aria-label={`Mở hoặc đóng kiến thức dự án ${project.name}`}
            >
              <div className="project-accordion-summary">
                <div className="project-accordion-heading">
                  <div className="min-w-0">
                    <h2>{project.name}</h2>
                    <span className="project-accordion-slug">
                      {project.slug}
                    </span>
                  </div>
                  <div className="project-accordion-badges">
                    <Badge
                      variant="outline"
                      className={cn(
                        project.is_active
                          ? "tt-badge-success tt-badge-soft border-transparent text-success"
                          : "border-border bg-muted/40 text-muted-foreground",
                      )}
                    >
                      {project.is_active ? "Đang hoạt động" : "Tắt"}
                    </Badge>
                    <Badge variant="outline">
                      {project.knowledge_mode === "DIRECT_CONTEXT"
                        ? "Một trang"
                        : "Theo danh mục"}
                    </Badge>
                  </div>
                </div>

                <dl className="project-accordion-facts">
                  <div>
                    <dt>
                      <FileText className="size-3.5" aria-hidden="true" />
                      Tài liệu
                    </dt>
                    <dd>{project.knowledge_document_count ?? 0}</dd>
                  </div>
                  <div>
                    <dt>
                      <CheckCircle2 className="size-3.5" aria-hidden="true" />
                      Sẵn sàng
                    </dt>
                    <dd>{readinessText}</dd>
                  </div>
                </dl>

                {(project.summary || project.index_card?.summary) && (
                  <p className="project-accordion-description">
                    {project.index_card?.summary ?? project.summary}
                  </p>
                )}
              </div>
            </AccordionTrigger>
            <AccordionContent className="project-accordion-content">
              {(canEdit || isAdmin) && (
                <div className="project-accordion-actions">
                  {canEdit && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => onEdit(project)}
                    >
                      <Pencil className="size-4" aria-hidden="true" />
                      Sửa dự án
                    </Button>
                  )}
                  {canEdit && onToggleActive && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={isTogglingActive}
                      aria-label={
                        project.is_active
                          ? `Tắt dự án ${project.name}`
                          : `Bật dự án ${project.name}`
                      }
                      onClick={() => onToggleActive(project)}
                    >
                      {project.is_active ? (
                        <PowerOff className="size-4" aria-hidden="true" />
                      ) : (
                        <Power className="size-4" aria-hidden="true" />
                      )}
                      {project.is_active ? "Tắt dự án" : "Bật dự án"}
                    </Button>
                  )}
                  {isAdmin && (
                    <DeleteButton
                      record={project}
                      resource="projects"
                      label="Xóa dự án"
                      size="sm"
                      variant="outline"
                      redirect={false}
                      successMessage="Đã xóa dự án."
                      mutationOptions={{ onSuccess: onDeleted }}
                    />
                  )}
                </div>
              )}
              <ProjectKnowledgePanel
                key={projectId}
                project={project}
                editable={canEdit}
                canManageSources={isAdmin}
              />
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
};

const ProjectAccordionSkeleton = () => (
  <div className="project-accordion-list" aria-label="Đang tải dự án">
    {Array.from({ length: 3 }).map((_, index) => (
      <Skeleton key={index} className="h-40 w-full rounded-xl" />
    ))}
  </div>
);

export const ProjectList = () => (
  <ListBase perPage={25} sort={{ field: "name", order: "ASC" }}>
    <ProjectListContent />
  </ListBase>
);
