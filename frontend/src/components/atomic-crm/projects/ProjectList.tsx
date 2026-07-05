import { useMemo, useState } from "react";
import { ListBase, useListContext, useRedirect, useRefresh } from "ra-core";
import { useMasterDetailSelection } from "../hooks/useMasterDetailSelection";
import { Boxes, Plus, Upload } from "lucide-react";
import { ListPagination } from "@/components/admin/list-pagination";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import type { Project } from "../types";
import { KnowledgeUpload } from "../knowledge/KnowledgeUpload";
import { useRoleActions } from "../hooks/useRoleActions";
import { BusTimetableSection } from "./ProjectBusTimetable";
import { ProjectOperationsPanel } from "./ProjectSidebar";
import { ProjectFeatures } from "./ProjectFeatures";
import { ProjectFaqEditor } from "./ProjectFaqEditor";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

const ProjectListContent = () => {
  const { data, isPending, total } = useListContext<Project>();
  const { isAdmin, canEdit } = useRoleActions();
  const refresh = useRefresh();
  const redirect = useRedirect();
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
  const projectTotal = total ?? projects.length;

  const selectedProject =
    projects.find((project) => project.id === selectedId) ??
    projects[0] ??
    null;

  return (
    <ProjectWorkspaceShell>
      <div className="project-workspace-content">
        <div className="ops-page-shell project-page-shell">
          <header className="ops-command-header project-command-header">
            <div className="ops-command-title">
              <div className="min-w-0">
                <p className="ops-kicker">Không gian dự án</p>
                <h1>Dự án tuyển dụng</h1>
                <p>Quản lý dự án, tài liệu training và trạng thái tư vấn.</p>
              </div>
            </div>
            <div className="project-command-actions">
              {isAdmin && (
                <>
                  <Button
                    variant="outline"
                    onClick={() => setUploadOpen(true)}
                    className="h-10 rounded-[8px]"
                  >
                    <Upload className="size-4" />
                    Tải tài liệu
                  </Button>
                  <Button
                    onClick={() => redirect("create", "projects")}
                    variant={projects.length > 0 ? "outline" : "default"}
                    className="h-10 rounded-[8px]"
                  >
                    <Plus className="size-4" />
                    Tạo dự án
                  </Button>
                </>
              )}
            </div>
          </header>

          {projects.length > 1 && (
            <section className="project-rollup-strip">
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

          <ProjectOperationsPanel
            projects={projects}
            selectedId={selectedId}
            selectedProject={selectedProject}
            isPending={isPending}
            isAdmin={isAdmin}
            canEdit={canEdit}
            onSelect={setSelectedId}
            onEdit={() =>
              selectedProject &&
              redirect("edit", "projects", selectedProject.id)
            }
            onDeleted={() => refresh()}
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

          {projectTotal > 25 && (
            <ListPagination
              rowsPerPageOptions={[10, 25, 50, 100]}
              className="ops-pagination"
            />
          )}
        </div>

        {isAdmin && (
          <KnowledgeUpload open={uploadOpen} onOpenChange={setUploadOpen} />
        )}
      </div>
    </ProjectWorkspaceShell>
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

export const ProjectList = () => (
  <ListBase perPage={25} sort={{ field: "name", order: "ASC" }}>
    <ProjectListContent />
  </ListBase>
);
