import { useEffect, useMemo, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import {
  ListBase,
  useDeleteWithUndoController,
  useListContext,
  useNotify,
  useRedirect,
  useRefresh,
  useUpdate,
} from "ra-core";
import {
  Boxes,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  EllipsisVertical,
  FileText,
  Pencil,
  Plus,
  Power,
  PowerOff,
  Trash2,
} from "lucide-react";
import { ListPagination } from "@/components/admin/list-pagination";
import { DeleteButton } from "@/components/admin";
import { useIsMobile } from "@/hooks/use-mobile";
import { MobilePageHeader } from "@/components/atomic-crm/kit/mobile-page-header";
import {
  AppModal,
  AppModalOverlay,
} from "@/components/atomic-crm/kit/app-modal";
import { Dialog } from "@/components/application/modals/modal";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import { ButtonUtility } from "@/components/base/buttons/button-utility";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "../kit";
import { Input } from "@/components/base/input/input";
import { Select } from "@/components/base/select/select";
import { Button as FilterButton } from "@/components/base/buttons/button";
import type { Project } from "../types";
import { useRoleActions } from "../hooks/useRoleActions";
import { ProjectKnowledgePanel } from "./ProjectKnowledgePanel";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";
import {
  aggregateProjectCategoryReadiness,
  projectActivationConflictVi,
  projectKnowledgeModeLabel,
  projectReadinessLabel,
} from "./domain/project-knowledge-policy";

const ProjectListContent = () => {
  const {
    data,
    isPending,
    error,
    total,
    page,
    perPage,
    setPage,
    filterValues,
    displayedFilters,
    setFilters,
  } = useListContext<Project>();
  const [query, setQuery] = useState(String(filterValues.q ?? ""));
  const [status, setStatus] = useState(
    typeof filterValues.is_active === "boolean"
      ? String(filterValues.is_active)
      : "all",
  );
  useEffect(() => setQuery(String(filterValues.q ?? "")), [filterValues.q]);
  useEffect(
    () =>
      setStatus(
        typeof filterValues.is_active === "boolean"
          ? String(filterValues.is_active)
          : "all",
      ),
    [filterValues.is_active],
  );
  const hasFilters =
    Boolean(filterValues.q) || typeof filterValues.is_active === "boolean";
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
        onError: (e) => {
          // The backend's frozen activation conflicts, already mapped to the
          // console's Vietnamese (see projectActivationConflictVi).
          notify(projectActivationConflictVi((e as Error).message), {
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
    () => aggregateProjectCategoryReadiness(projects),
    [projects],
  );

  const projectTotal = total ?? projects.length;
  const isMobile = useIsMobile();
  // The phone card list opens the knowledge panel in the kit bottom sheet;
  // the desktop accordion keeps its inline expandable panel.
  const [sheetProject, setSheetProject] = useState<Project | null>(null);
  const createButton = isAdmin ? (
    <Button
      size="sm"
      onClick={() => redirect("create", "projects")}
      className="project-create-button"
      aria-label="Tạo dự án"
    >
      <Plus className="size-4" aria-hidden="true" />
      Tạo dự án
    </Button>
  ) : null;

  return (
    <ProjectWorkspaceShell>
      <div className="project-workspace-content">
        <div className="ops-page-shell project-page-shell">
          {isMobile ? (
            <MobilePageHeader
              title="Dự án tuyển dụng"
              primaryAction={createButton}
            />
          ) : (
            <header className="ops-command-header project-command-header">
              <div className="ops-command-title">
                <div className="min-w-0">
                  <h1>Dự án tuyển dụng</h1>
                  <p>Quản lý tuyển dụng và kiến thức tư vấn cho từng dự án.</p>
                </div>
              </div>
              <div className="project-command-actions">{createButton}</div>
            </header>
          )}

          <ProjectDirectoryFilters
            query={query}
            status={status}
            onQueryChange={(next) => {
              setQuery(next);
              setFilters(
                {
                  ...filterValues,
                  q: next,
                  is_active: status === "all" ? undefined : status === "true",
                },
                displayedFilters,
                true,
              );
            }}
            onStatusChange={(next) => {
              setStatus(next);
              setFilters(
                {
                  ...filterValues,
                  q: query,
                  is_active: next === "all" ? undefined : next === "true",
                },
                displayedFilters,
                true,
              );
            }}
            onClear={() => {
              setQuery("");
              setStatus("all");
              setFilters({}, displayedFilters, true);
            }}
          />

          {projects.length > 0 && (
            <section
              className="project-rollup-strip"
              aria-label="Tóm tắt dự án"
            >
              <span>
                {projectTotal} dự án{hasFilters ? " phù hợp" : ""}
              </span>
              <span>Trang này: {activeCount} đang bật</span>
              <span>{documentCount} tài liệu trên trang</span>
              <span>
                {readiness.total > 0
                  ? `${readiness.ready}/${readiness.total} tiêu chí tư vấn trên trang`
                  : "Chưa đo độ sẵn sàng"}
              </span>
            </section>
          )}

          {error ? (
            <div role="alert" className="project-directory-error">
              <p>
                Không tải được danh sách dự án. Kiểm tra kết nối rồi thử lại.
              </p>
              <Button variant="outline" onClick={refresh}>
                Thử lại
              </Button>
            </div>
          ) : isPending ? (
            <ProjectAccordionSkeleton />
          ) : projects.length > 0 ? (
            isMobile ? (
              <ProjectMobileCardList
                projects={projects}
                isAdmin={isAdmin}
                canEdit={canEdit}
                onEdit={(project) => redirect("edit", "projects", project.id)}
                onDeleted={() => refresh()}
                onToggleActive={toggleActive}
                isTogglingActive={isTogglingActive}
                onOpenKnowledge={(project) => setSheetProject(project)}
              />
            ) : (
              <ProjectAccordionList
                projects={projects}
                isAdmin={isAdmin}
                canEdit={canEdit}
                onEdit={(project) => redirect("edit", "projects", project.id)}
                onDeleted={() => refresh()}
                onToggleActive={toggleActive}
                isTogglingActive={isTogglingActive}
              />
            )
          ) : (
            <EmptyState
              icon={<Boxes className="size-6" />}
              title={hasFilters ? "Không có dự án phù hợp" : "Chưa có dự án"}
              description={
                hasFilters
                  ? "Thử tên khác hoặc xóa bộ lọc để xem tất cả dự án."
                  : "Tạo dự án mới hoặc tải kiến thức để trợ lý có ngữ cảnh tư vấn."
              }
              className="min-h-[420px]"
            />
          )}

          {(projectTotal > perPage || page > 1) &&
            (isMobile ? (
              <ProjectMobilePagination
                page={page}
                perPage={perPage}
                total={projectTotal}
                setPage={setPage}
              />
            ) : (
              <ListPagination
                rowsPerPageOptions={[10, 25, 50, 100]}
                className="ops-pagination"
              />
            ))}
        </div>
      </div>
      {sheetProject ? (
        <AppModalOverlay
          isOpen
          onOpenChange={(nextOpen) => {
            if (!nextOpen) setSheetProject(null);
          }}
          isDismissable
          className="uu-scope"
        >
          <AppModal className="project-knowledge-sheet w-full outline-hidden sm:max-w-md">
            <Dialog
              aria-label={`Kiến thức dự án ${sheetProject.name}`}
              className="outline-hidden"
            >
              <div className="project-knowledge-sheet-body uu-scope">
                <ProjectKnowledgePanel
                  project={sheetProject}
                  editable={canEdit}
                  canManageSources={isAdmin}
                />
              </div>
            </Dialog>
          </AppModal>
        </AppModalOverlay>
      ) : null}
    </ProjectWorkspaceShell>
  );
};

/**
 * Row actions for one phone card, in the kit's base `Dropdown` (the
 * LeadCardList idiom). Delete rides `useDeleteWithUndoController` — the same
 * undo-notification flow the desktop `DeleteButton` uses, so data verbs and
 * copy stay identical across anatomies.
 */
const ProjectCardMenu = ({
  project,
  isAdmin,
  canEdit,
  onEdit,
  onToggleActive,
  isTogglingActive,
  onDeleted,
}: {
  project: Project;
  isAdmin: boolean;
  canEdit: boolean;
  onEdit: (project: Project) => void;
  onToggleActive?: (project: Project) => void;
  isTogglingActive?: boolean;
  onDeleted: () => void;
}) => {
  const { isPending: isDeleting, handleDelete } = useDeleteWithUndoController({
    record: project,
    resource: "projects",
    redirect: false,
    mutationOptions: { onSuccess: onDeleted },
    successMessage: "Đã xóa dự án.",
  });

  return (
    <Dropdown.Root>
      <ButtonUtility
        size="sm"
        color="tertiary"
        className="uu-scope project-card-menu-trigger"
        aria-label={`Thao tác khác cho dự án ${project.name}`}
        icon={<EllipsisVertical aria-hidden="true" />}
      />
      <Dropdown.Popover placement="bottom end" offset={8} className="uu-scope">
        <Dropdown.Menu>
          {canEdit ? (
            <Dropdown.Item
              id={`project-edit-${project.id}`}
              label="Sửa dự án"
              icon={Pencil}
              onPress={() => onEdit(project)}
            />
          ) : null}
          {canEdit && onToggleActive ? (
            <Dropdown.Item
              id={`project-toggle-${project.id}`}
              label={project.is_active ? "Tắt dự án" : "Bật dự án"}
              icon={project.is_active ? PowerOff : Power}
              onPress={() => onToggleActive(project)}
            />
          ) : null}
          {isAdmin ? (
            <Dropdown.Item
              id={`project-delete-${project.id}`}
              label="Xóa dự án"
              icon={Trash2}
              isDisabled={isDeleting || isTogglingActive}
              onPress={(event) =>
                void handleDelete(event as unknown as ReactMouseEvent)
              }
            />
          ) : null}
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown.Root>
  );
};

/**
 * Phone directory: one tappable card per project (title + meta badges), row
 * actions in the base Dropdown. Tapping the card opens the knowledge panel in
 * the bottom sheet — the phone counterpart of the desktop accordion's
 * expandable panel.
 */
export const ProjectMobileCardList = ({
  projects,
  isAdmin,
  canEdit,
  onEdit,
  onToggleActive,
  isTogglingActive = false,
  onDeleted,
  onOpenKnowledge,
}: {
  projects: Project[];
  isAdmin: boolean;
  canEdit: boolean;
  onEdit: (project: Project) => void;
  onToggleActive?: (project: Project) => void;
  isTogglingActive?: boolean;
  onDeleted: () => void;
  onOpenKnowledge: (project: Project) => void;
}) => (
  <ul className="project-card-list" role="list">
    {projects.map((project) => {
      const activeBadge = projectActiveBadge(project);
      const ingestBadge = projectIngestBadge(project);

      return (
        <li key={String(project.id)}>
          <div className="project-card">
            <button
              type="button"
              className="project-card-main"
              // Compound row surface (envelope opt-out): the compact-step clamp
              // and the 40px ceiling pinned this button at 40px while its title
              // + badge row needs ~62px, spilling the badges past the card
              // background (CHAT-18).
              data-allow-tall
              aria-label={`Mở kiến thức dự án ${project.name}`}
              onClick={() => onOpenKnowledge(project)}
            >
              <h2 className="project-card-title">{project.name}</h2>
              <span className="project-card-badges">
                <Badge variant="outline" className={activeBadge.className}>
                  {activeBadge.label}
                </Badge>
                {ingestBadge ? (
                  <Badge variant="outline" className={ingestBadge.className}>
                    {ingestBadge.label}
                  </Badge>
                ) : null}
              </span>
            </button>
            <ProjectCardMenu
              project={project}
              isAdmin={isAdmin}
              canEdit={canEdit}
              onEdit={onEdit}
              onToggleActive={onToggleActive}
              isTogglingActive={isTogglingActive}
              onDeleted={onDeleted}
            />
          </div>
        </li>
      );
    })}
  </ul>
);

/** Two 44px page steppers and a compact "x / y" label. */
const ProjectMobilePagination = ({
  page,
  perPage,
  total,
  setPage,
}: {
  page: number;
  perPage: number;
  total: number;
  setPage: (page: number) => void;
}) => {
  const lastPage = Math.max(1, Math.ceil(total / perPage));

  return (
    <nav className="project-mobile-pagination" aria-label="Phân trang dự án">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="project-mobile-page-btn"
        aria-label="Trang trước"
        disabled={page <= 1}
        onClick={() => setPage(page - 1)}
      >
        <ChevronLeft className="size-4" aria-hidden="true" />
      </Button>
      <span className="project-mobile-pagination-label">
        {page} / {lastPage}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="project-mobile-page-btn"
        aria-label="Trang sau"
        disabled={page >= lastPage}
        onClick={() => setPage(page + 1)}
      >
        <ChevronRight className="size-4" aria-hidden="true" />
      </Button>
    </nav>
  );
};

const PROJECT_STATUS_OPTIONS = [
  { id: "all", label: "Tất cả dự án" },
  { id: "true", label: "Đang tuyển dụng" },
  { id: "false", label: "Chưa bật tuyển dụng" },
];

export const ProjectDirectoryFilters = ({
  query,
  status,
  onQueryChange,
  onStatusChange,
  onClear,
}: {
  query: string;
  status: string;
  onQueryChange: (query: string) => void;
  onStatusChange: (status: string) => void;
  onClear: () => void;
}) => (
  <section
    className="uu-scope project-directory-filters"
    aria-label="Tìm và lọc dự án"
  >
    <Input
      label="Tìm dự án"
      name="project-search"
      type="search"
      value={query}
      onChange={onQueryChange}
      placeholder="Tên, mã hoặc nội dung dự án…"
    />
    <Select
      label="Trạng thái tuyển dụng"
      popoverClassName="uu-scope console-select-popover"
      items={PROJECT_STATUS_OPTIONS}
      selectedKey={status}
      onSelectionChange={(key) => onStatusChange(String(key))}
    >
      {(item) => <Select.Item id={item.id}>{item.label}</Select.Item>}
    </Select>
    {(query || status !== "all") && (
      <FilterButton color="secondary" size="md" onClick={onClear}>
        Xóa bộ lọc
      </FilterButton>
    )}
  </section>
);

// Availability badge — the state recruiters scan for: is the bot offering
// this project to candidates right now. Always rendered, first in the group.
const projectActiveBadge = (
  project: Project,
): { label: string; className: string } =>
  project.is_active
    ? {
        label: "Đang bật",
        className:
          "tt-badge-success tt-badge-soft border-transparent text-success",
      }
    : {
        label: "Đã tắt",
        className: "border-border bg-muted/40 text-muted-foreground",
      };

// Ingest badge driven by the list payload's `ingest_state`; null when the
// payload says nothing about ingest — availability has its own badge.
const projectIngestBadge = (
  project: Project,
): { label: string; className: string } | null => {
  switch (project.ingest_state) {
    case "ingesting":
      return {
        label: "Đang nạp",
        className: "tt-badge-secondary tt-badge-soft border-transparent",
      };
    case "error":
      return {
        label: "Lỗi nạp",
        className:
          "tt-badge-error tt-badge-soft border-transparent text-destructive",
      };
    case "ready":
      if (project.knowledge_document_count === 0) {
        return {
          label: "Chưa nạp",
          className: "border-border bg-muted/40 text-muted-foreground",
        };
      }
      return {
        label: "Đã nạp",
        className:
          "tt-badge-success tt-badge-soft border-transparent text-success",
      };
    default:
      return null;
  }
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
        const activeBadge = projectActiveBadge(project);
        const ingestBadge = projectIngestBadge(project);

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
                    {/* Availability leads: the enabled/disabled state the
                        recruiter scans for; ingest follows when known. */}
                    <Badge variant="outline" className={activeBadge.className}>
                      {activeBadge.label}
                    </Badge>
                    {ingestBadge && (
                      <Badge
                        variant="outline"
                        className={ingestBadge.className}
                      >
                        {ingestBadge.label}
                      </Badge>
                    )}
                    <Badge variant="outline">
                      {projectKnowledgeModeLabel(project.knowledge_mode)}
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
                      Thông tin tư vấn
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
              {!project.is_active &&
                (project.ingest_state === "ingesting" ||
                  project.ingest_state === "error") && (
                  <p className="text-helper text-muted-foreground">
                    Hoàn tất nạp và xử lý lỗi kiến thức trước khi bật tuyển
                    dụng.
                  </p>
                )}
              <ProjectKnowledgePanel
                key={projectId}
                project={project}
                editable={canEdit}
                canManageSources={isAdmin}
                toolbar={
                  canEdit || isAdmin ? (
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
                          disabled={
                            isTogglingActive ||
                            (!project.is_active &&
                              (project.ingest_state === "ingesting" ||
                                project.ingest_state === "error"))
                          }
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
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              aria-label={`Thao tác khác cho dự án ${project.name}`}
                            >
                              <EllipsisVertical
                                className="size-4"
                                aria-hidden="true"
                              />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem asChild>
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
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </div>
                  ) : undefined
                }
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
